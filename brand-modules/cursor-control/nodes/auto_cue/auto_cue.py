#! /usr/bin/env python
# %%
import gc
import logging
import time
import json

import numpy as np
from brand import BRANDNode


class AutoCue(BRANDNode):

    def __init__(self):

        super().__init__()

        # initialize in/out stream parameters
        self.input_stream = self.parameters['input_stream'].encode()
        self.output_stream = self.parameters['output_stream']
        if 'output_vect_name' in self.parameters:
            self.output_vect_name = self.parameters['output_vect_name']
        else:
            self.output_vect_name = ''

        # initialize target parameters
        self.target_stream = self.parameters['target_stream'].encode()
        self.target_list = self.parameters['target_list']
        self.target_dtype = self.parameters['target_dtype']
        self.target_on_off = self.parameters['target_on_off']
        if 'target_state_dtype' in self.parameters:
            self.target_state_dtype = self.parameters['target_state_dtype']
        else:
            self.target_state_dtype = self.target_dtype
        self.target_off_center = self.parameters['target_off_center']
        if 'target_move_state' in self.parameters:
            self.target_move_state = self.parameters['target_move_state']
        else:
            self.target_move_state = 1

        # initialize movement parameters
        self.move_stream = self.parameters['move_stream'].encode()
        self.move_list = self.parameters['move_list']
        self.move_dtype = self.parameters['move_dtype']
        self.speed = self.parameters['speed'] / self.parameters[
            'input_rate']  # convert speed in units/sec to units/iteration
        self.vel_profile = self.parameters['vel_profile']
        self.vel_output = self.parameters['vel_output']

        if len(self.target_list) != len(self.move_list):
            logging.error('target_list and move_list must be of equal length')

        # define auto-cue parameters for different velocity profiles
        if self.vel_profile == 'triangular':
            if 'min_speed' not in self.parameters:
                logging.error(
                    f"{self.vel_profile} velocity profile requires a 'min_speed' parameter"
                )
            self.min_speed = self.parameters['min_speed']
        if self.vel_profile == 'gaussian':
            if 'min_speed' not in self.parameters:
                logging.error(
                    f"{self.vel_profile} velocity profile requires a 'min_speed' parameter"
                )
            self.min_speed = self.parameters['min_speed']
        if self.vel_profile == 'PD':
            if 'pd_kp' not in self.parameters or 'pd_kd' not in self.parameters:
                logging.error(
                    f"{self.vel_profile} velocity profile requires both 'pd_kp' and 'pk_kd' terms parameters"
                )
            self.Kp = self.parameters['pd_kp']
            self.Kd = self.parameters['pd_kd']

        logging.info(f'Velocity profile: {self.vel_profile}')

        # initialize optional trigger
        if 'triggered' in self.parameters:
            self.triggered = self.parameters['triggered']
            self.trigger_stream = self.parameters['trigger_stream']
        else:
            self.triggered = False

        logging.info(
            f'Movement start triggered by external movement device?: {self.triggered}'
        )

        # define timing and sync keys
        self.sync_key = self.parameters['sync_key'].encode()
        self.time_key = self.parameters['time_key'].encode()

        # initialize input stream entry data
        self.input_id = '$'

        logging.info(
            f'Refresh triggered by input from stream: {self.input_stream}')

        # initialize variables
        self.move_data = {k: 0 for k in self.move_list}
        self.target_data = {k: 0 for k in self.target_list}
        self.target_data[self.target_on_off] = 0

        self.move_vec = np.empty(len(self.move_list), dtype=self.move_dtype)
        self.move_start_vec = np.empty(len(self.move_list),
                                       dtype=self.move_dtype)
        self.target_vec = np.empty(len(self.target_list),
                                   dtype=self.target_dtype)
        self.target_last_vec = np.empty(len(self.target_list),
                                        dtype=self.target_dtype)

        # general auto-cue parameters and utility variables
        self.error_thres = self.parameters['error_thres']
        self.error_last = 0
        self.iter = 0

        self.target_init = False
        self.move_init = False
        self.moving = False

        # initialize output stream entry data
        self.index = np.uint64(0)

        logging.info(f'Starting auto_cue node')

    def work(self):

        # wait for neural data input
        replies = self.r.xread({self.input_stream: self.input_id},
                               count=1,
                               block=0)
        entries = replies[0][1]
        self.input_id, entry_data = entries[0]
        self.label = json.loads(entry_data[self.sync_key])

        # get target location
        self.last_target = self.r.xrevrange(self.target_stream, '+', '-', 1)
        if len(self.last_target) > 0:
            entry_id, entry_dict = self.last_target[0]
            self.target_data = {}
            for key in self.target_list:
                if key.encode() in entry_dict:
                    self.target_data[key] = np.frombuffer(
                        entry_dict[key.encode()],
                        dtype=self.target_dtype).item()
                    self.target_init = True
                else:
                    logging.error(
                        f'{key} not found in {self.target_stream} stream')
            if self.target_on_off.encode() in entry_dict:
                self.target_data[self.target_on_off] = np.frombuffer(
                    entry_dict[self.target_on_off.encode()],
                    dtype=self.target_state_dtype).item()
            else:
                logging.error(
                    f'{self.target_on_off} not found in {self.target_stream} stream'
                )

        # get movement location
        self.last_move = self.r.xrevrange(self.move_stream, '+', '-', 1)
        if len(self.last_move) > 0:
            entry_id, entry_dict = self.last_move[0]
            self.move_data = {}
            for key in self.move_list:
                if key.encode() in entry_dict:
                    self.move_data[key] = np.frombuffer(
                        entry_dict[key.encode()],
                        dtype=self.move_dtype).item()
                    # if self.move_init == False:
                    #     logging.info(f'first move data: {self.move_data}')
                    self.move_init = True
                else:
                    logging.error(
                        f'{key} not found in {self.move_stream} stream')

        if self.triggered:
            self.last_trigger = self.r.xrevrange(self.trigger_stream, '+', '-',
                                                 1)
            if len(self.last_trigger) > 0:
                entry_id, entry_dict = self.last_trigger[0]
                if np.frombuffer(entry_dict[b'samples'], np.uint8) > 0:
                    self.moving = True
        else:
            self.moving = True

        # calculate direction of movement
        self.curr_vec = np.array([self.move_data[k] for k in self.move_list],
                                 dtype=self.move_dtype)

        if self.target_data[
                self.
                target_on_off] >= self.target_move_state:  # target is on, move to target
            self.target_vec = np.array(
                [self.target_data[k] for k in self.target_list],
                dtype=self.target_dtype)
        elif self.target_off_center:  # target is off, move to center
            self.target_vec = np.zeros(len(self.target_list),
                                       dtype=self.target_dtype)
        else:  # target is off, stay put
            self.target_vec = self.curr_vec
            self.moving = False

        if self.moving and self.target_init and self.move_init:

            # logging.debug(f'Target vec last: ({self.target_last_vec}) --current move vec: ({self.target_last_vec})')
            # update start position for this movement
            if np.any(np.isnan(self.target_last_vec)):
                self.move_start_vec = self.curr_vec
                logging.debug(f'New move vec start: ({self.move_start_vec})')
            elif np.linalg.norm(self.target_vec -
                                self.target_last_vec) > self.error_thres:
                self.move_start_vec = self.curr_vec
                logging.debug(f'New move vec start: ({self.move_start_vec})')
            self.target_last_vec = self.target_vec

            # compute partial and total vectors and magnitudes/distances
            self.move_vec = self.target_vec - self.curr_vec
            self.move_mag = np.linalg.norm(self.move_vec)
            self.total_move_vec = self.target_vec - self.move_start_vec
            self.total_move_dist = np.linalg.norm(self.total_move_vec)

            #logging.debug(f'target vec: ({self.target_vec}) -- curr vec: ({self.curr_vec}) -- move start vec: ({self.move_start_vec})')
            #logging.debug(f'Total move dist: ({self.total_move_dist})')

            if self.vel_profile == "constant":

                if self.move_mag > self.error_thres:
                    self.move_dir = self.move_vec / self.move_mag
                else:
                    self.move_dir = np.zeros(len(self.move_list),
                                             dtype=self.move_dtype)

                # if distance to target is less than constant speed delta, cap movement delta at distance to target
                self.gain = self.move_mag if self.move_mag < self.speed else self.speed

                # movement velocity to apply
                self.move_vel = self.gain * self.move_dir

            elif self.vel_profile == "triangular":

                # if position is being held (i.e. for a delay)
                if np.all(self.move_vec == self.total_move_vec):
                    self.iter = 0

                # compute move direction and triangular speed profile
                if self.move_mag > self.error_thres and self.total_move_dist > 0:
                    T = np.ceil(
                        self.total_move_dist / self.speed
                    )  # maximum number of iterations to complete movement
                    self.move_dir = self.move_vec / self.move_mag
                    # before halfway point
                    if self.iter < 0.5 * T:
                        vel_gain = self.iter / (0.25 * T)
                    # after halfway point
                    else:
                        vel_gain = (T - self.iter) / (0.25 * T)
                    self.move_speed_i = self.min_speed + (
                        self.speed - self.min_speed) * vel_gain
                else:
                    self.move_dir = np.zeros(len(self.move_list),
                                             dtype=self.target_dtype)
                    self.move_speed_i = 0

                self.iter += 1

                # check if speed is below minimum threshold and set to minimum value
                self.move_speed_i = np.maximum(self.move_speed_i,
                                               self.min_speed)

                # if distance to target is less than speed delta, cap movement delta at distance to target
                self.gain = self.move_mag if self.move_mag < self.move_speed_i else self.move_speed_i

                logging.debug(f'Movement speed: ({self.move_speed_i})')

                # cursor velocity to apply
                self.move_vel = self.gain * self.move_dir

            elif self.vel_profile == "gaussian":

                # if position is being held (i.e. for a delay)
                if np.all(self.move_vec == self.total_move_vec):
                    self.iter = 0

                # compute move direction and triangular speed profile
                if self.move_mag > self.error_thres and self.total_move_dist > 0:
                    T = np.ceil(
                        self.total_move_dist / self.speed
                    )  # maximum number of iterations to complete movement
                    self.move_dir = self.move_vec / self.move_mag

                    # truncated gaussian parameters
                    sigma = T / 6
                    mu = sigma * 3
                    # NOTE: might be good to save this value somewhere to not compute every loop
                    scale = sum(
                        np.exp(-((np.arange(0, T) - mu)**2 / (2 * sigma**2))) /
                        (sigma * np.sqrt(2 * np.pi)))

                    vel_gain = np.exp(-(
                        (self.iter - mu)**2 /
                        (2 * sigma**2))) / (sigma * np.sqrt(2 * np.pi)) / scale

                    self.move_speed_i = self.min_speed + (
                        self.speed - self.min_speed
                    ) * vel_gain * T  # should this be T or the sample rate?
                else:
                    self.move_dir = np.zeros(len(self.move_list),
                                             dtype=self.target_dtype)
                    self.move_speed_i = 0

                self.iter += 1

                # check if speed is below minimum threshold and set to minimum value
                self.move_speed_i = np.maximum(self.move_speed_i,
                                               self.min_speed)

                # if distance to target is less than speed delta, cap movement delta at distance to target
                self.gain = self.move_mag if self.move_mag < self.move_speed_i else self.move_speed_i

                logging.debug(f'Movement speed: ({self.move_speed_i})')

                # cursor velocity to apply
                self.move_vel = self.gain * self.move_dir

            elif self.vel_profile == "PD":

                self.d_error = self.move_vec - self.error_last

                self.move_vel = self.Kp * self.error + self.Kd * self.d_error

                self.error_last = self.error

            else:
                self.move_vel = np.zeros(len(self.move_list),
                                         dtype=self.move_dtype)

        else:
            self.move_vel = np.zeros(len(self.move_list),
                                     dtype=self.move_dtype)

        # move to target
        if not self.vel_output:  # if position output
            self.move_vel += self.curr_vec

        # if we want to output a vector
        if self.output_vect_name != '':
            output_kin = {self.output_vect_name: self.move_vel.tobytes()}
        else:
            output_kin = {
                m: v.tobytes()
                for m, v in zip(self.move_list, self.move_vel)
            }

        self.r.xadd(
            self.output_stream, {
                **output_kin, self.sync_key: json.dumps(self.label),
                self.time_key: np.uint64(time.monotonic_ns()).tobytes(),
                b'i': self.index.tobytes()
            })

        self.index += np.uint64(1)


if __name__ == "__main__":
    gc.disable()

    # setup
    auto_cue = AutoCue()

    # main
    auto_cue.run()

    gc.collect()

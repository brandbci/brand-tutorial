#!/usr/bin/env python
# -*- coding: utf-8 -*-
# simulatorFSM.py
"""
RadialFSM.py

Keeps track of the behavioral state machine. This will take the
inputs from whatever input we want, take care of the necessary gains
and offsets, keep track of the current cursor and target(s) and
send all of that appropriate information to the Redis stream for the
graphics controller.

@author: Yahia Ali, Mattia Rigotti, Kevin Bodkin
"""
import gc
import json
import logging
import time
from struct import pack

import numpy as np
from brand import BRANDNode


# defining the cursors, targets etc
# define target
class Target():
    # one instance for each target -- with a state to say whether the target is
    # off, on, or if the cursor is over the target

    def __init__(self,
                 x,
                 y,
                 radius=50,
                 connected_targets=[],
                 is_start=False,
                 id=None):
        self.state = 0  # always start with everything off
        self.x = x
        self.y = y
        self.radius = radius
        self.connected_targets = connected_targets
        self.is_start = is_start
        self.id = id
        self.visited_targets = []

    def off(self):  # to turn the state 'off'
        self.state = 0

    def show(self):  # to turn the state to 'show'
        self.state = 1

    def on(self):  # to turn the state to 'on'
        self.state = 2

    def over(self):
        self.state = 3  # to turn the state to 'over'

    def is_over(self, curs):
        self.on()
        dx = self.x - curs.x  # center everything on the target
        dy = self.y - curs.y
        center_dist = np.sqrt(dx**2 + dy**2)
        # if the cursor is within the target's range
        if center_dist < self.radius + curs.radius:
            self.over()
            return True
        else:
            return False

    def pack(self, index, sync_dict, sync_key, time_key):
        sync_dict_json = json.dumps(sync_dict)
        targetDict = {
            b'X': pack('f', self.x),
            b'Y': pack('f', self.y),
            b'radius': pack('f', self.radius),
            b'state': pack('i', self.state),
            b'i': np.uint32(index).tobytes(),
            sync_key: sync_dict_json.encode(),
            time_key: np.uint64(time.monotonic_ns()).tobytes()
        }
        return targetDict

    def pick_target(self, targets):
        available_targets = [
            t for t in self.connected_targets if t not in self.visited_targets
        ]
        new_target = np.random.choice(available_targets)
        self.visited_targets.append(new_target)
        if len(self.visited_targets) == len(self.connected_targets):
            self.visited_targets = []
        return targets[new_target]


# define the cursor
class Cursor():
    # initialize
    def __init__(self, x=0, y=0, gain_x=1, gain_y=1, radius=25):
        self.mX = gain_x
        self.mY = gain_y
        self.radius = radius
        # we'll pack the three output values (state, x and y)
        # into a single byte string later to send to redis
        self.state = 0  # always start with everything off
        self.x = x  # just initialization
        self.y = y
        self.i = 0
        self.i_in = -1
        self.x_bounds = [-960, 960]
        self.y_bounds = [-540, 540]

    def set_bounds(self, x_bounds, y_bounds):
        self.x_bounds = x_bounds
        self.y_bounds = y_bounds

    def off(self):
        self.state = 0

    def on(self):
        self.state = 1

    def update_cursor(self, dx, dy, pressed):
        self.x += dx * self.mX
        self.x = np.clip(self.x, self.x_bounds[0], self.x_bounds[1])
        self.y += dy * self.mY
        self.y = np.clip(self.y, self.y_bounds[0], self.y_bounds[1])
        self.is_pressed = pressed

    def recenter(self):
        self.x = 0
        self.y = 0

    def pack(self, index, sync_dict, sync_key, time_key):
        sync_dict_json = json.dumps(sync_dict)
        cursorDict = {
            b'X': pack('f', self.x),
            b'Y': pack('f', self.y),
            b'radius': pack('f', self.radius),
            b'state': pack('i', int(self.state)),
            b'i': np.uint32(index).tobytes(),
            sync_key: sync_dict_json.encode(),
            time_key: np.uint64(time.monotonic_ns()).tobytes()
        }
        return cursorDict

    def printCurs(self):
        logging.info("X: " + str(self.x) + ", Y: " + str(self.y))


# storing timing info for between tasks, hold times etc
class DelayGenerator():

    def __init__(self, min_delay=0, max_delay=0):
        self.min = min_delay
        self.max = max_delay
        self.current = (np.random.random() * (self.max - self.min)) + self.min

    def reroll(self):
        self.current = (np.random.random() * (self.max - self.min)) + self.min


def pick_target(targets, target_keys):
    return targets[np.random.choice(list(target_keys))]


# state definition
STATE_BETWEEN_TRIALS = 0
STATE_START_TRIAL = 1
STATE_MOVEMENT = 2


class RadialFSM(BRANDNode):

    def __init__(self):

        super().__init__()

        logging.info('Initializing targets and cursors')

        # initialize target list
        self.targets = {}  # a list to hold all of the targets

        target_diameter = self.parameters['target_diameter']
        target_radius = target_diameter / 2
        distance_from_center = self.parameters['distance_from_center']

        out_target_list = {}
        for i, angle in enumerate(self.parameters['target_angles']):
            out_target_list[f'{i + 1}'] = {
                'x': np.round(distance_from_center * np.cos(np.radians(angle)),
                              4),
                'y': np.round(distance_from_center * np.sin(np.radians(angle)),
                              4),
            }

        self.center = self.targets['0'] = Target(x=0,
                                                 y=0,
                                                 radius=target_radius,
                                                 connected_targets=sorted(
                                                     out_target_list.keys()),
                                                 is_start=True,
                                                 id='0')

        # load in all of the targets
        for key, values in out_target_list.items():
            self.targets[key] = Target(**values,
                                       radius=target_radius,
                                       connected_targets=['0'],
                                       is_start=False,
                                       id=key)

        # set cursor bounds
        if 'cursor_x_bounds' in self.parameters:
            cursor_x_bounds = self.parameters['cursor_x_bounds']
        else:
            cursor_x_bounds = [-960, 960]
        if 'cursor_y_bounds' in self.parameters:
            cursor_y_bounds = self.parameters['cursor_y_bounds']
        else:
            cursor_y_bounds = [-540, 540]

        # initialize cursor at center
        self.curs = Cursor(x=0,
                           y=0,
                           gain_x=1,
                           gain_y=1,
                           radius=self.parameters['cursor_radius'])
        self.curs.set_bounds(cursor_x_bounds, cursor_y_bounds)

        self.recenter = self.parameters['recenter']
        self.recenter_on_fail = self.parameters['recenter_on_fail']

        self.initial_wait_time = self.parameters['initial_wait_time']

        # initialize wait times

        # time between trials
        self.inter_trial_time_in = DelayGenerator(
            min_delay=self.parameters['inter_trial_time_in']['min'],
            max_delay=self.parameters['inter_trial_time_in']['max'])
        self.inter_trial_time_out = DelayGenerator(
            min_delay=self.parameters['inter_trial_time_out']['min'],
            max_delay=self.parameters['inter_trial_time_out']['max'])
        self.inter_trial_time_failure = DelayGenerator(
            min_delay=self.parameters['inter_trial_time_failure']['min'],
            max_delay=self.parameters['inter_trial_time_failure']['max'])

        # how long do they have to wait before go cue?
        self.delay_time_in = DelayGenerator(
            min_delay=self.parameters['delay_time_in']['min'],
            max_delay=self.parameters['delay_time_in']['max'])
        self.delay_time_out = DelayGenerator(
            min_delay=self.parameters['delay_time_out']['min'],
            max_delay=self.parameters['delay_time_out']['max'])

        # how long do they have to hold the target?
        self.target_hold_time_in = DelayGenerator(
            min_delay=self.parameters['target_hold_time_in']['min'],
            max_delay=self.parameters['target_hold_time_in']['max'])
        self.target_hold_time_out = DelayGenerator(
            min_delay=self.parameters['target_hold_time_out']['min'],
            max_delay=self.parameters['target_hold_time_out']['max'])

        if 'trial_timeout' in self.parameters:
            self.timeout_time = self.parameters['trial_timeout']
        else:
            self.timeout_time = 10

        # initialize trigger stream check
        if 'check_trigger' in self.parameters:
            self.check_trigger = self.parameters['check_trigger']
        else:
            self.check_trigger = False
        if 'trigger_stream' in self.parameters:
            self.trigger_stream = self.parameters['trigger_stream']

        # initialize stream info

        self.input_stream = self.parameters['input_stream'].encode()
        self.mouse_id = '$'

        self.sync_key = self.parameters['sync_key'].encode()
        self.time_key = self.parameters['time_key'].encode()

        self.sync_dict = {}
        self.sync_dict_json = json.dumps(self.sync_dict)
        self.i = 0

        # redis entry to the state stream
        self.state_entry = {
            self.time_key: np.uint64(time.monotonic_ns()).tobytes(),
            self.sync_key: self.sync_dict_json.encode(),
            b'state': b'start_trial',
            b'i': np.uint32(self.i).tobytes()
        }

        # redis entry to the success stream
        self.trial_success_entry = {
            self.time_key: np.uint64(time.monotonic_ns()).tobytes(),
            self.sync_key: self.sync_dict_json.encode(),
            b'success': np.uint8(1).tobytes(),
            b'i': np.uint32(self.i).tobytes()
        }

        # redis entry to the trial_info stream
        self.trial_info_entry = {
            self.time_key: np.uint64(time.monotonic_ns()).tobytes(),
            self.sync_key: self.sync_dict_json.encode(),
            b'target_X': np.float32(0).tobytes(),
            b'target_Y': np.float32(0).tobytes(),
            b'reach_angle': np.float32(0).tobytes(),
            b'start_X': np.float32(0).tobytes(),
            b'start_Y': np.float32(0).tobytes(),
            b'cond_id': b'0-0',
            b'target_radius': np.float32(0).tobytes(),
            b'cursor_radius': np.float32(0).tobytes(),
            b'dwell_time': np.float32(0).tobytes(),
            b'i': np.uint32(self.i).tobytes()
        }

    def run(self):

        # start at the center
        self.tgt = self.center

        # initialize FSM
        self.state = STATE_BETWEEN_TRIALS
        self.tgt.off()
        self.curs.on()
        self.state_time = time.monotonic()
        self.inter_trial_time = self.initial_wait_time
        self.delay_time = 0
        self.target_hold_time = 0.5

        self.prev_target = self.tgt
        self.trial_count = 0

        logging.info('Starting center-out FSM')

        # main loop
        while True:

            # read from cursor control stream
            reply = self.r.xread({self.input_stream: self.mouse_id},
                                 block=0,
                                 count=1)
            entries = reply[0][1]
            self.mouse_id, cursorFrame = entries[0]

            # pulling data in
            sync_dict_in = json.loads(cursorFrame[self.sync_key].decode())
            self.sync_dict = sync_dict_in

            sensors = np.frombuffer(cursorFrame[b'samples'],
                                    dtype=self.parameters['input_dtype'])
            sensor_x, sensor_y = sensors
            sensor_click = 0

            self.curs.update_cursor(sensor_x, sensor_y,
                                    sensor_click)  # sensor names

            # the posix time at the beginning of the loop
            self.curr_time = time.monotonic()

            p = self.r.pipeline()

            self.sync_dict_json = json.dumps(self.sync_dict)

            self.state_entry[self.sync_key] = self.sync_dict_json.encode()
            self.state_entry[self.time_key] = np.uint64(
                time.monotonic_ns()).tobytes()
            self.state_entry[b'i'] = np.uint32(self.i).tobytes()

            self.trial_success_entry[
                self.sync_key] = self.sync_dict_json.encode()
            self.trial_success_entry[self.time_key] = np.uint64(
                time.monotonic_ns()).tobytes()
            self.trial_success_entry[b'i'] = np.uint32(self.i).tobytes()

            self.trial_info_entry[self.sync_key] = self.sync_dict_json.encode()
            self.trial_info_entry[self.time_key] = np.uint64(
                time.monotonic_ns()).tobytes()
            self.trial_info_entry[b'i'] = np.uint32(self.i).tobytes()

            if self.state == STATE_BETWEEN_TRIALS:
                if (self.curr_time - self.state_time) > self.inter_trial_time:
                    self.state = STATE_START_TRIAL
                    # reroll times for current target
                    if self.tgt.is_start:
                        self.delay_time_in.reroll()
                        self.target_hold_time_in.reroll()
                        self.delay_time = self.delay_time_in.current
                        self.target_hold_time = (
                            self.target_hold_time_in.current)
                    else:
                        self.delay_time_out.reroll()
                        self.target_hold_time_out.reroll()
                        self.delay_time = self.delay_time_out.current
                        self.target_hold_time = (
                            self.target_hold_time_out.current)
                    self.prev_target = self.tgt
                    # reroll times for next target
                    self.tgt = self.prev_target.pick_target(self.targets)
                    if self.tgt.is_start:
                        self.inter_trial_time_in.reroll()
                        self.inter_trial_time = (
                            self.inter_trial_time_in.current)
                    else:
                        self.inter_trial_time_out.reroll()
                        self.inter_trial_time = (
                            self.inter_trial_time_out.current)
                    self.tgt.show()
                    self.trial_count += 1
                    self.state_time = self.curr_time
                    self.state_entry[b'state'] = 'start_time'
                    p.xadd(b'state', self.state_entry)
                    self.trial_info_entry[b'target_X'] = pack('f', self.tgt.x)
                    self.trial_info_entry[b'target_Y'] = pack('f', self.tgt.y)
                    self.trial_info_entry[b'start_X'] = pack(
                        'f', self.prev_target.x)
                    self.trial_info_entry[b'start_Y'] = pack(
                        'f', self.prev_target.y)
                    self.trial_info_entry[b'cond_id'] = (
                        str(self.prev_target.id) + "-" +
                        str(self.tgt.id)).encode()
                    self.trial_info_entry[b'target_radius'] = pack(
                        'f', self.tgt.radius)
                    self.trial_info_entry[b'cursor_radius'] = pack(
                        'f', self.curs.radius)
                    self.trial_info_entry[b'dwell_time'] = pack(
                        'f', self.target_hold_time)
                    p.xadd(b'trial_info', self.trial_info_entry)
                    logging.info(
                        f'{self.trial_count} - New trial started, '
                        f'reaching for target [{self.tgt.x},{self.tgt.y}]')

            elif self.state == STATE_START_TRIAL:
                # check whether there was movement in the delay period
                moved_during_delay = False
                if self.check_trigger:
                    self.last_trigger = self.r.xrevrange(
                        self.trigger_stream, '+', '-', 1)
                    if len(self.last_trigger) > 0:
                        _, entry_dict = self.last_trigger[0]
                        if np.frombuffer(entry_dict[b'samples'], np.uint8) > 0:
                            moved_during_delay = True
                #elif not self.prev_target.is_over(self.curs):
                #    moved_during_delay = True

                # if there was movement, fail the trial
                if moved_during_delay:
                    # fail trial
                    self.state = STATE_BETWEEN_TRIALS
                    self.tgt.off()
                    self.state_time = self.curr_time
                    self.state_entry[b'state'] = 'end_time'
                    p.xadd(b'state', self.state_entry)
                    self.trial_success_entry[b'success'] = np.uint8(
                        0).tobytes()
                    p.xadd(b'trial_success', self.trial_success_entry)
                    logging.info(f'{self.trial_count} - Moved during delay'
                                 ', starting new trial')
                    # revert to previous target
                    self.tgt = self.prev_target
                    # define fail specific inter trial time
                    self.inter_trial_time_failure.reroll()
                    self.inter_trial_time = (
                        self.inter_trial_time_failure.current)

                # if delay time has passed, transition to movement state
                if (self.curr_time - self.state_time) > self.delay_time:
                    self.state = STATE_MOVEMENT
                    self.tgt.on()
                    self.state_time = self.curr_time
                    self.last_out_of_target_time = self.curr_time
                    self.state_entry[b'state'] = 'go_cue_time'
                    p.xadd(b'state', self.state_entry)
                    logging.info(f'{self.trial_count} - Trial go cue')

            elif self.state == STATE_MOVEMENT:
                if (self.curr_time - self.state_time) > self.timeout_time:
                    # fail trial
                    self.state = STATE_BETWEEN_TRIALS
                    self.tgt.off()
                    self.state_time = self.curr_time
                    self.state_entry[b'state'] = 'end_time'
                    p.xadd(b'state', self.state_entry)
                    self.trial_success_entry[b'success'] = np.uint8(
                        0).tobytes()
                    p.xadd(b'trial_success', self.trial_success_entry)
                    logging.info(
                        f'{self.trial_count} - Timeout, starting new trial')
                    if self.recenter_on_fail:
                        # recenter on failure
                        self.tgt = self.center
                        self.curs.recenter()
                    else:
                        # revert to previous target
                        self.tgt = self.prev_target
                    # define fail specific inter trial time
                    self.inter_trial_time_failure.reroll()
                    self.inter_trial_time = self.inter_trial_time_failure.current
                else:
                    if self.tgt.is_over(self.curs):
                        # if cursor over target and hold time has passed, end trial
                        if ((self.curr_time - self.last_out_of_target_time) >
                                self.target_hold_time):
                            self.state = STATE_BETWEEN_TRIALS
                            self.tgt.off()
                            self.state_time = self.curr_time
                            self.state_entry[b'state'] = 'end_time'
                            p.xadd(b'state', self.state_entry)
                            self.trial_success_entry[b'success'] = np.uint8(
                                1).tobytes()
                            p.xadd(b'trial_success', self.trial_success_entry)
                            logging.info(
                                f'{self.trial_count} - Target '
                                f'[{self.tgt.x},{self.tgt.y}] acquired'
                                ', trial ended')
                            if self.recenter:
                                self.tgt = self.center
                                self.curs.recenter()
                                self.inter_trial_time_in.reroll()
                                self.inter_trial_time = (
                                    self.inter_trial_time_in.current)
                    else:
                        # reset the time over the target
                        self.last_out_of_target_time = self.curr_time

            p.xadd(
                b'cursorData',
                self.curs.pack(self.i, self.sync_dict, self.sync_key,
                               self.time_key))
            p.xadd(
                b'targetData',
                self.tgt.pack(self.i, self.sync_dict, self.sync_key,
                              self.time_key))

            p.execute()

            self.i += 1


if __name__ == "__main__":
    gc.disable()

    # setup
    radial_fsm = RadialFSM()

    # main
    radial_fsm.run()

    gc.collect()

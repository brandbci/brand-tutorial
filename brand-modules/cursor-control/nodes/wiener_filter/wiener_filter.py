#!/usr/bin/env python
# -*- coding: utf-8 -*-
# wiener_filter.py
import gc
import logging
import os
import pickle
import signal
import sys
import time

import numpy as np
from brand import BRANDNode
from sklearn.linear_model import Ridge

NAME = 'wiener_filter'  # name of this node


class Decoder(BRANDNode):

    def __init__(self):
        super().__init__()
        # build the wiener_filter
        self.n_features = self.parameters['n_features']
        self.n_targets = self.parameters['n_targets']
        self.seq_len = self.parameters['seq_len']
        self.in_stream = self.parameters['input_stream']
        self.in_field = self.parameters['input_field']
        self.in_dtype = self.parameters['input_dtype']
        self.out_stream = self.parameters['output_stream'].encode()
        self.out_field = self.parameters['output_field'].encode()
        self.out_dtype = self.parameters['output_dtype']

        # stream containing the list of channels to use
        if 'ch_mask_stream' in self.parameters:
            self.ch_mask_stream = self.parameters['ch_mask_stream']
        self.zero_masked_chans = (self.parameters['zero_masked_chans']
                                  if 'zero_masked_chans' in self.parameters
                                  else False)
        self.excl_chans = (self.parameters['excl_chans']
                           if 'excl_chans' in self.parameters else None)

        # define timing and sync keys
        if 'sync_key' in self.parameters:
            self.sync_key = self.parameters['sync_key'].encode()
        else:
            self.sync_key = b'sync'
        if 'time_key' in self.parameters:
            self.time_key = self.parameters['time_key'].encode()
        else:
            self.time_key = b'ts'

        self.build()

        # initialize IDs for the two Redis streams
        self.data_id = '$'
        self.param_id = '$'

        # terminate on SIGINT
        signal.signal(signal.SIGINT, self.terminate)

    def build(self):
        self.load_channel_mask()

        self.model_path = self.parameters['model_path']
        logging.info(f"Attempting to load model from file {self.model_path}")
        try:
            with open(self.model_path, 'rb') as f:
                self.mdl = pickle.load(f)
                logging.info(f'Loaded model from {self.model_path}')
        except Exception:
            logging.warning(
                'Failed to load wiener_filter. Initializing a new one.')
            self.mdl = Ridge()
            X = np.ones((100, self.n_features * self.seq_len))
            y = np.ones((100, self.n_targets))
            self.mdl.fit(X, y)

    def load_channel_mask(self):
        # initialize the channel mask to include all channels
        self.ch_mask = np.arange(self.n_features)
        # remove channels specified in excl_chans
        if self.excl_chans:
            self.ch_mask = np.setdiff1d(self.ch_mask, self.excl_chans)

        # get list of masked channels
        if hasattr(self, 'ch_mask_stream'):
            ch_mask_entry = self.r.xrevrange(self.ch_mask_stream,
                                             '+',
                                             '-',
                                             count=1)
            if ch_mask_entry:
                stream_mask = np.frombuffer(ch_mask_entry[0][1][b'channels'],
                                            dtype=np.uint16)
                self.ch_mask = np.intersect1d(self.ch_mask, stream_mask)
                logging.info("Loaded channel mask from stream "
                             f"{self.ch_mask_stream}")
                if not self.zero_masked_chans:  # masked channels are dropped
                    logging.info('Overriding n_features parameter '
                                 f'{self.n_features} with {len(self.ch_mask)}')
                    self.n_features = len(self.ch_mask)
            else:
                logging.warning(
                    f"'ch_mask_stream' was set to {self.ch_mask_stream}, but "
                    "there were no entries. Defaulting to using all channels")
                self.ch_mask = np.arange(self.n_features)
        self.ch_mask.sort()
        logging.info(self.ch_mask)

    def predict(self, x):
        # implementing this step directly instead of using mdl.predict() for
        # best performance
        y = x.dot(self.mdl.coef_.T) + self.mdl.intercept_
        return y

    def run(self):
        input_stream = self.in_stream.encode()
        input_dtype = self.in_dtype
        input_field = self.in_field.encode()
        # initialize variables
        # entry to the decoder output stream
        decoder_entry = {
            self.time_key: np.uint64(time.monotonic_ns()).tobytes(),
            'i': int(),
            'i_in': int(),
            self.out_field: np.zeros(self.n_targets + 1,
                                     self.out_dtype).tobytes(),
            'n_features': self.n_features,
            'n_targets': self.n_targets,
        }
        # input stream
        stream_dict = {input_stream: self.data_id}

        # current window of data to use for decoding
        window = np.zeros((self.seq_len, self.n_features), dtype=input_dtype)
        # binned decoder input
        X = np.zeros((1, self.n_features * self.seq_len), dtype=input_dtype)
        # decoder output
        y = np.zeros((1, self.n_targets), dtype=self.out_dtype)

        i = 0
        i_in = -1
        while True:
            # read from the function generator stream
            streams = self.r.xread(stream_dict, block=0, count=1)
            _, stream_entries = streams[0]
            self.data_id, entry_dict = stream_entries[0]
            # load the input
            neural = np.frombuffer(entry_dict[input_field], dtype=input_dtype)
            if self.zero_masked_chans:
                # window is the size of neural, so mask it as well
                window[0, self.ch_mask] = neural[self.ch_mask]
            else:
                # window is the size of ch_mask
                window[0, :] = neural[self.ch_mask]
            i_in = entry_dict[b'i']
            stream_dict[input_stream] = self.data_id

            X[0, :] = window.reshape(1, self.n_features * self.seq_len)
            # generate a prediction
            y[0, :] = self.predict(X).astype(self.out_dtype)[0]

            # write results to Redis
            decoder_entry[self.time_key] = np.uint64(
                time.monotonic_ns()).tobytes()
            decoder_entry['i'] = np.uint64(i).tobytes()
            decoder_entry['i_in'] = i_in
            decoder_entry[self.out_field] = y.tobytes()
            if self.sync_key in entry_dict:
                decoder_entry[self.sync_key] = entry_dict[self.sync_key]
            self.r.xadd(self.out_stream, decoder_entry)

            # shift window along the history axis
            window[1:, :] = window[:-1, :]
            i += 1

    def terminate(self, sig, frame):
        logging.info('SIGINT received, Exiting')
        gc.collect()
        sys.exit(0)


if __name__ == "__main__":
    gc.disable()

    # setup
    logging.info(f'PID: {os.getpid()}')
    dec = Decoder()

    # main
    dec.run()

    gc.collect()

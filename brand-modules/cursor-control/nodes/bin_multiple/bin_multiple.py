#!/usr/bin/env python
# -*- coding: utf-8 -*-
# bin_multiple.py
import gc
import json
import logging
import time

import numpy as np
from brand import BRANDNode
from brand.redis import xread_sync


class BinThresholds(BRANDNode):

    def __init__(self):

        super().__init__()

        # initialize parameters
        self.chan_per_stream = self.parameters['chan_per_stream']
        self.bin_size = self.parameters['bin_size']
        self.input_streams = self.parameters['input_streams']
        self.input_field = self.parameters['input_field'].encode()
        self.input_dtype = self.parameters['input_dtype']
        self.output_stream = self.parameters['output_stream']
        self.sync_field = self.parameters['sync_field']

        # initialize input stream entry data
        self.stream_dict = {name.encode(): '$' for name in self.input_streams}

        logging.info(f'Reading from streams: {self.input_streams}')

        # define timing and sync keys
        self.time_key = 'ts'.encode()
        self.sync_key = 'sync'.encode()

        # initialize output stream entry data
        self.i = 0
        self.window = np.zeros(
            (self.chan_per_stream * len(self.input_streams), self.bin_size),
            dtype=np.int8)

        self.output_entry = {}
        self.output_entry['samples'] = self.window.sum(axis=1).astype(
            np.int8).tobytes()
        self.output_entry['i'] = self.i

        logging.info(f'Start spike binning from 1ms to {self.bin_size}ms...')

    def run(self):
        # field to use f
        sync_field = (self.sync_field.encode()
                      if self.sync_field else self.sync_field)
        # count the number of entries we have read into the bin so far
        self.n_entries = 0

        while True:

            # reset number of entries into the bin
            self.n_entries = 0

            self.sync_entries = []

            # read `bin_size` samples from stream
            if sync_field:
                streams = xread_sync(self.r,
                                     self.stream_dict,
                                     block=0,
                                     sync_field=sync_field,
                                     sync_dtype=np.uint32,
                                     count=self.bin_size)
            else:
                streams = self.r.xread(self.stream_dict,
                                       block=0,
                                       count=self.bin_size)
            for i_stream, stream in enumerate(streams):
                stream_name, stream_entries = stream
                ch = slice(i_stream * self.chan_per_stream,
                           (i_stream + 1) * self.chan_per_stream)
                sync_entries_stream = []
                for i, (entry_id, entry_dict) in enumerate(stream_entries):
                    # load the input
                    self.window[ch, i] = np.frombuffer(
                        entry_dict[self.input_field], dtype=self.input_dtype)
                    # log sync for this entry
                    sync_entries_stream.append(
                        json.loads(entry_dict[b'sync'].decode()))
                self.sync_entries.append(sync_entries_stream)
                # update the xread ID
                self.stream_dict[stream_name] = entry_id

            # create sync dict from sync entries from input streams
            sync_dict = {}
            for stream in self.sync_entries:
                sync_entry_dict = stream[0]  # first entry from each stream
                for key in sync_entry_dict:
                    sync_dict[key] = sync_entry_dict[key]
            sync_dict_json = json.dumps(sync_dict)

            # write results to Redis
            self.output_entry[self.time_key] = np.uint64(
                time.monotonic_ns()).tobytes()
            self.output_entry[self.sync_key] = sync_dict_json
            self.output_entry['samples'] = self.window.sum(axis=1).astype(
                np.int8).tobytes()
            self.output_entry['i'] = np.uint64(self.i).tobytes()

            self.r.xadd(self.output_stream, self.output_entry)

            self.i += 1


if __name__ == "__main__":
    gc.disable()

    # setup
    bin_thresholds = BinThresholds()

    # main
    bin_thresholds.run()

    gc.collect()

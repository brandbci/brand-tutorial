# BRAND Tutorial

This repository contains a brief tutorial on how to get started using BRAND. The tutorial consists of the following steps:
1. Set up your system for BRAND by following the instructions in [00_setup.md](./notebooks/00_setup.md)
2. Run a calibration task and train a decoder using [01_calibration.ipynb](./notebooks/01_calibration.ipynb)
3. Run a closed-loop cursor control task with your trained decoder using [02_control.ipynb](./notebooks/02_control.ipynb)
4. If you have multiple machines on whicn you can run BRAND, try out the multi-machine version of this task with [03_multi_machine.ipynb](./notebooks/02_multi_machine.ipynb)

Once you have finished the above steps, you will have a working example of how to use BRAND to run an experiment.

Next, you may want to:   
- Learn how graphs are configured (see docs in [brand/README.md](brand/README.md) and examples in [notebooks/graphs](notebooks/graphs))
- Write finite-state machine and graphics nodes to fit the task of your choice (see [radialFSM.py](brand-modules/cursor-control/nodes/radialFSM/radialFSM.py) and [display_centerOut.py](brand-modules/cursor-control/nodes/display_centerOut/display_centerOut.py))
- Try out a new decoder architecture (see [wiener_filter.py](brand-modules/cursor-control/nodes/wiener_filter/wiener_filter.py))
- Acquire data from a neural recording device like a Blackrock Neurotech Neural Signal Processor (NSP) (see [cerebusAdapter.c](brand-modules/brand-nsp/nodes/cerebusAdapter/cerebusAdapter.c))

If you run into any issues, please document and submit them here on GitHub.

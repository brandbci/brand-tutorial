# Setup
## System Requirements
### Operating system
This set of tutorials was designed and tested on Ubuntu 20.04 LTS. Newer versions of Ubuntu should work as well but they have not been tested. Other Linux distributions, particularly those that do not use `apt` for package management, may require modifications to the the installation commands.

### Kernel
This tutorial was tested on `Linux 5.15.0` (standard) and `Linux 5.15.43-rt45` (fully-preemptible) kernels. Other kernel versions are expected to work without issue, but, for timing-critical applications, we recommend using a fully-preemptible kernel. Fully-preemptible kernels help prevent high-priority processes from being interrupted by lower-priority ones, which helps make code execution times more predictable.

Instructions on installing a fully-preemptible version of the Linux kernel can be found [here](../brand/doc/preempt_rt.md).

### Permissions
Due to security restrictions on changing Linux process priorities and configuring Redis, running BRAND currently requires `sudo` permissions.

### Libraries
We use [miniconda](https://docs.conda.io/en/latest/miniconda.html) for Python environment management. If you are using Anaconda, the installation commands will be identical. If you do not have either miniconda or anaconda, you will need to [install](https://conda.io/projects/conda/en/stable/user-guide/install/linux.html) one of them to proceed with the tutorial.

The file [bootstrap.sh](../brand/bootstrap.sh) installs system-level packages required by BRAND and sets up the `rt` conda enviroment. Run this after you have installed miniconda.

We install Redis from source using the version that is pinned to the BRAND repository [here](../brand/lib/redis). If you have installed Redis using another method like `apt`, you may run into version incompatibility issues. To install Redis and compile BRAND nodes, run `make` from the [`brand`](../brand) directory.

## Installation Checklist
1. Install Ubuntu 20.04 LTS
2. Install a fully-preemptible Linux kernel (optional)
3. Grant sudo permissions to your user account
4. Install `miniconda`
5. Install BRAND dependencies (run [bootstrap.sh](../brand/bootstrap.sh))
6. Run `source setup.sh` from the `brand` directory
7. Compile Redis and BRAND nodes (run `make` from the `brand` directory)

## Running BRAND
BRAND uses two Python scripts to launch and manage processes: [supervisor](../brand/lib/python/brand/supervisor.py) and [booter](../brand/lib/python/brand/booter.py). `supervisor` is the main one, and it handles loading configuration parameters, starting Redis, and starting and stopping nodes. If you are running BRAND on just one machine, you will only need to use `supervisor`. If you want to run BRAND nodes on several machines at a time, you will run `supervisor` on the "host" machine that contains the Redis database and run `booter` on any other "client" machines that will be running nodes.

To start supervisor:
1. Enter the `brand` directory: `cd brand`
2. Run `source setup.sh`
3. Run `supervisor`. To view configuration options, run `supervisor -h`

To start `booter`:
1. Log into your client machine and navigate to the `brand` directory
2. Run `source setup.sh`
3. Run `booter -m $MACHINE`, replacing `$MACHINE` with a unique name for each computer. Use the `-i` and `-p` options to specify a Redis IP and port that match those in the `supervisor` start command.

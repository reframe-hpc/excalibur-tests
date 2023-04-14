import os

# Some systems, notably some Cray-based ones, don't have access to the home filesystem.
# This means that if you set up Spack in your bashrc script, this file won't be loaded and
# the job will fail because it can't find `spack`.  This function allows propagating the
# setting of `PATH` on the node which submits the benchmark to script generated by ReFrame.
def spack_root_to_path():
    spack_root = os.getenv('SPACK_ROOT')
    path = os.getenv('PATH')
    if spack_root is None:
        return path
    else:
        spack_bindir = os.path.join(spack_root, 'bin')
        if path is None:
            return dir
        else:
            if spack_bindir in path.split(os.path.pathsep):
                return path
            else:
                return spack_bindir * os.path.pathsep * path

site_configuration = {
    'systems': [
        {
            # https://www.archer2.ac.uk/about/hardware.html
            # https://docs.archer2.ac.uk/
            'name': 'archer2',
            'descr': 'ARCHER2',
            'hostnames': ['ln[0-9]+'],
            'modules_system': 'lmod',
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'ARCHER2 compute nodes',
                    'scheduler': 'slurm',
                    'launcher': 'srun',
                    'env_vars': [
                        # Propagate PATH to compute nodes, including `spack` bindir
                        ['PATH', spack_root_to_path()],
                        # Work around for Spack erroring out on non-existing home directory:
                        # https://github.com/spack/spack/issues/33265#issuecomment-1277343920
                        ['SPACK_USER_CONFIG_PATH', os.path.expanduser("~").replace('home', 'work')],
                        ['SPACK_USER_CACHE_PATH',  os.path.expanduser("~").replace('home', 'work')],
                    ],
                    'access': ['--partition=standard'],
                    'environs': ['default'],
                    'max_jobs': 64,
                    'processor': {
                        'num_cpus': 128,
                        'num_cpus_per_core': 1,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 64,
                    }
                },
            ]
        },  # end ARCHER2
        {
            # https://www.hpc.cam.ac.uk/systems/peta-4
            'name': 'csd3-skylake',
            'descr': 'CSD3 Skylake',
            'hostnames': ['login-e-[0-9]+'],
            'modules_system': 'tmod32',
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'Skylake compute nodes',
                    'scheduler': 'slurm',
                    'launcher': 'mpirun',
                    'access': ['--partition=skylake'],
                    'environs': ['default'],
                    'max_jobs': 64,
                    'processor': {
                        'num_cpus': 32,
                        'num_cpus_per_core': 2,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 16,
                    }
                },
            ]
        },  # end CSD3 Skylake
        {
            # https://www.hpc.cam.ac.uk/systems/peta-4
            'name': 'csd3-icelake',
            'descr': 'CSD3 Icelake',
            'hostnames': ['login-q-[0-9]+'],
            'modules_system': 'tmod4',
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'Icelake compute nodes',
                    'scheduler': 'slurm',
                    'launcher': 'mpirun',
                    'access': ['--partition=icelake'],
                    'environs': ['default', 'intel2020-csd3'],
                    'max_jobs': 64,
                    'processor': {
                        'num_cpus': 76,
                        'num_cpus_per_core': 1,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 38,
                    },
                },
            ]
        },  # end CSD3 Icelake
        {
            # https://www.rc.ucl.ac.uk/docs/Clusters/Myriad/#node-types
            'name': 'myriad',
            'descr': 'Myriad',
            'hostnames': ['login[0-9]+.myriad.ucl.ac.uk'],
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'Computing nodes',
                    'scheduler': 'sge',
                    'launcher': 'mpirun',
                    'environs': ['default'],
                    'max_jobs': 36,
                    'features': ['gpu'],
                    'processor': {
                        'num_cpus': 36,
                        'num_cpus_per_core': 1,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 18,
                    },
                    'resources': [
                        {
                            'name': 'mpi',
                            'options': ['-pe mpi {num_slots}'],
                        },
                        {
                            'name': 'gpu',
                            'options': ['-l gpu={num_gpus_per_node}'],
                        },
                    ],
                },
            ],
        },  # end Myriad
        {
            # https://gw4-isambard.github.io/docs/user-guide/MACS.html
            'name': 'isambard-cascadelake',
            'descr': 'Cascade Lake nodes of Isambard 2',
            'hostnames': ['login-0[12].gw4.metoffice.gov.uk'],
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'Cascadelake computing nodes',
                    'scheduler': 'pbs',
                    'launcher': 'mpirun',
                    'access': ['-q clxq'],
                    'environs': ['default'],
                    'max_jobs': 20,
                    'processor': {
                        'num_cpus': 40,
                        'num_cpus_per_core': 1,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 20,
                    },
                },
            ]
        },  # end Isambard Cascadelake
        {
            # https://gw4-isambard.github.io/docs/user-guide/A64FX.html
            'name': 'isambard-a64fx',
            'descr': 'A64FX nodes of Isambard 2',
            'hostnames': ['gw4a64fxlogin[0-9]+'],
            'partitions': [
                {
                    'name': 'a64fx',
                    'descr': 'A64FX computing nodes',
                    'scheduler': 'pbs',
                    'launcher': 'mpirun',
                    'access': ['-q a64fx'],
                    'environs': ['default'],
                    'max_jobs': 20,
                    'processor': {
                        'num_cpus': 48,
                        'num_cpus_per_core': 1,
                        'num_sockets': 1,
                        'num_cpus_per_socket': 48,
                    },
                },
            ]
        },  # end Isambard A64FX
        {
            # https://gw4-isambard.github.io/docs/user-guide/XCI.html
            'name': 'isambard-xci',
            'descr': 'XCI - Marvell Thunder X2 nodes of Isambard 2',
            'hostnames': ['xcil0[0-1]'],
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'XCI computing nodes',
                    'scheduler': 'pbs',
                    'launcher': 'alps',
                    'access': ['-q arm'],
                    'environs': ['default'],
                    'max_jobs': 20,
                    'processor': {
                        'num_cpus': 256,
                        'num_cpus_per_core': 4,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 128,
                    },
                },
            ]
        },  # end Isambard XCI
        {
            # https://www.dur.ac.uk/icc/cosma/support/cosma8/
            'name': 'cosma8',
            'descr': 'COSMA',
            'hostnames': ['login[0-9][a-z].pri.cosma[0-9].alces.network'],
            'modules_system': 'tmod4',
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'Compute nodes',
                    'scheduler': 'slurm',
                    'launcher': 'mpiexec',
                    'access': ['--partition=cosma8'],
                    'environs': ['default', 'intel20-mpi-durham', 'intel20_u2-mpi-durham', 'intel19-mpi-durham', 'intel19_u3-mpi-durham'],
                    'sched_options': {
                        'use_nodes_option': True,
                    },
                    'max_jobs': 64,
                    'processor': {
                        'num_cpus': 128,
                        'num_cpus_per_core': 1,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 64,
                    },
                }
            ]
        },  # end cosma8
        {
            'name': 'github-actions',
            'descr': 'GitHub Actions runner',
            'hostnames': ['fv-az.*'],  # Just to not have '.*'
            'partitions': [
                {
                    'name': 'default',
                    'scheduler': 'local',
                    'launcher': 'mpirun',
                    'environs': ['default']
                }
            ]
        },  # End GitHub Actions
        {
            # https://epcced.github.io/dirac-docs/tursa-user-guide/scheduler/#partitions
            'name': 'tursa',
            'descr': 'Tursa',
            'hostnames': ['tursa-login.*'],
            'partitions': [
                {
                    'name': 'gpu',
                    'descr': 'GPU computing nodes',
                    'scheduler': 'slurm',
                    'launcher': 'mpirun',
                    'access': ['--partition=gpu', '--qos=standard'],
                    'environs': ['default'],
                    'features': ['gpu'],
                    'sched_options': {
                        'use_nodes_option': True,
                    },
                    'max_jobs': 16,
                    'processor': {
                        'num_cpus': 64,
                        'num_cpus_per_core': 2,
                        'num_sockets': 1,
                        'num_cpus_per_socket': 32,
                    },
                    'resources': [
                        {
                            'name': 'gpu',
                            'options': ['--gres=gpu:{num_gpus_per_node}']
                        },
                    ],
                },
            ]
        },  # end Tursa
        {
            # https://dial3-docs.dirac.ac.uk/About_dial3/architecture/
            'name': 'dial3',
            'descr': 'Dirac Data Intensive @ Leicester',
            'hostnames': ['d3-login.*'],
            'modules_system': 'lmod',
            'partitions': [
                {
                    'name': 'compute-node',
                    'descr': 'Computing nodes',
                    'scheduler': 'slurm',
                    'launcher': 'mpirun',
                    'environs': ['default', 'intel-oneapi-openmpi-dial3','intel19-mpi-dial3'],
                    'max_jobs': 64,
                    'processor': {
                        'num_cpus': 128,
                        'num_cpus_per_core': 1,
                        'num_sockets': 2,
                        'num_cpus_per_socket': 64,
                    },
                },
            ]
        },  # end DiaL3
        {
            'name': 'generic',
            'descr': 'generic',
            'hostnames': ['.*'],
            'partitions': [
                {
                    'name': 'default',
                    'descr': 'Default system',
                    'scheduler': 'local',
                    'launcher': 'mpirun',
                    'environs': ['default'],
                },
            ]
        },  # end generic
        # < insert new systems here >
    ],
    'environments': [
        {
            # Since we always build with spack, we are not using the compilers in this environment.
            # The compilers spack uses are definied in the spack specs of the reframe config
            # for each app. Nevertheless, we have to define an environment here to make ReFrame happy.
            'name': 'default',
            'cc': 'cc',
            'cxx': 'c++',
            'ftn': 'ftn'
        },
        {
            'name': 'intel20-mpi-durham',
            'modules':['intel_comp/2020','intel_mpi/2020'],
            'cc': 'mpiicc',
            'cxx': 'mpiicpc',
            'ftn': 'mpiifort'
        },
        {
            'name': 'intel20_u2-mpi-durham',
            'modules':['intel_comp/2020-update2','intel_mpi/2020-update2'],
            'cc': 'mpiicc',
            'cxx': 'mpiicpc',
            'ftn': 'mpiifort'
        },
        {
            'name': 'intel19-mpi-durham',
            'modules':['intel_comp/2019','intel_mpi/2019'],
            'cc': 'mpiicc',
            'cxx': 'mpiicpc',
            'ftn': 'mpiifort'
        },
        {
            'name': 'intel19_u3-mpi-durham',
            'modules':['intel_comp/2019-update3','intel_mpi/2019-update3'],
            'cc': 'mpiicc',
            'cxx': 'mpiicpc',
            'ftn': 'mpiifort'
        },
        {
            'name':'intel-oneapi-openmpi-dial3',
            'modules':['intel-oneapi-compilers/2021.2.0','openmpi4/intel/4.0.5'],
            'cc':'mpicc',
            'cxx':'mpicxx',
            'ftn':'mpif90'
        },
        {
            'name': 'intel19-mpi-dial3',
            'modules':['intel-parallel-studio/cluster.2019.5'],
            'cc': 'mpiicc',
            'cxx': 'mpiicpc',
            'ftn': 'mpiifort'
        },
        {
            'name': 'intel2020-csd3',
            'modules': ["intel/compilers/2020.4",
                        "intel/mkl/2020.4",
                        "intel/impi/2020.4/intel",
                        "intel/libs/idb/2020.4",
                        "intel/libs/tbb/2020.4",
                        "intel/libs/ipp/2020.4",
                        "intel/libs/daal/2020.4",
                        "intel/bundles/complib/2020.4"],
            'cc': 'mpiicc',
            'cxx': 'mpiicpc',
            'ftn': 'mpiifort'
        },
    ],
    'logging': [
        {
            'level': 'debug',
            'handlers': [
                {
                    'type': 'stream',
                    'name': 'stdout',
                    'level': 'info',
                    'format': '%(message)s'
                },
                {
                    'type': 'file',
                    'level': 'debug',
                    'format': '[%(asctime)s] %(levelname)s: %(check_info)s: %(message)s',   # noqa: E501
                    'append': False
                }
            ],
            'handlers_perflog': [
                {
                    'type': 'filelog',
                    'prefix': '%(check_system)s/%(check_partition)s',
                    'level': 'info',
                    'format': (
                        '%(check_job_completion_time)s|'
                        'reframe %(version)s|'
                        '%(check_info)s|'
                        '%(check_jobid)s|'
                        '%(check_num_tasks)s|'
                        '%(check_num_cpus_per_task)s|'
                        '%(check_num_tasks_per_node)s|'
                        '%(check_num_gpus_per_node)s|'
                        '%(check_perfvalues)s|'
                        '%(check_spack_spec)s|'
                        '%(check_env_vars)s'
                    ),
                    'format_perfvars': (
                        '%(check_perf_value)s|'
                        '%(check_perf_unit)s|'
                        '%(check_perf_ref)s|'
                        '%(check_perf_lower_thres)s|'
                        '%(check_perf_upper_thres)s|'
                    ),
                    'append': True
                }
            ]
        }
    ],
}

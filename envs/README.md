# Environment notes

The locked study was not executed in one universally interchangeable environment. GraphST, STAGATE, SpaGCN, and BANKSY used the Python package set represented by `analysis-four-methods.yml`. SEDR additionally required R, mclust, rpy2, deterministic CUDA controls, and a distinct package freeze represented by `sedr.yml` and `sedr-r.yml`. The MERFISH four-method run metadata records CPU execution with PyTorch `2.13.0+cpu`; a complete standalone MERFISH package freeze was not preserved and is therefore **TO VERIFY**.

The root `environment.yml` and `requirements.txt` are convenient reconstructions from the recorded four-method lock. They do not silently resolve the SEDR/R environment or guarantee compatibility across CUDA driver generations. For strongest fidelity, use the split files.

The original host used Python 3.11.9 on Windows 10 build 10.0.26200. The recorded GPU was an NVIDIA GeForce RTX 5060 Laptop GPU with 8,151 MiB memory, driver 582.05, and CUDA compute capability 12.0. The SEDR environment reported CUDA runtime 12.8. Do not infer that a GPU is required for every method: BANKSY and SpaGCN were run on CPU in the frozen four-method runner, while GraphST used CUDA when available; STAGATE device selection depended on the panel and available environment.

PyTorch CUDA wheel resolution is platform-specific. The recorded wheel was `torch 2.11.0+cu128`; the environment files specify the package version while the local installer must select the CUDA 12.8-compatible channel/index appropriate to the platform.


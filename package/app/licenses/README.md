# Third-party notices

- The FPK includes the Python GGUF reader from [llama.cpp at 3cf0325](https://github.com/ggml-org/llama.cpp/tree/3cf03257f219afbe7334045ff7c6a06ac68c627d/gguf-py). Its MIT license is included at `engines/strata/control/gguf-py/LICENSE`.

- Strata Control 0.1.59.1 and engine 0.1.59 come from the [Strata 0.2.13 release](https://github.com/Niko1221/Strata/releases/tag/v0.2.13). See `Strata-MIT.txt` and the ggml and sFNX notices in this directory. The fnOS build adjusts the OpenAI Chat Completions integration in Control. The engine files retain their upstream bytes.
- The engine includes NVIDIA CUDA 13.0 runtime and cuBLAS libraries (`libcudart.so.13`, `libcublas.so.13` and `libcublasLt.so.13`). These files are subject to the [NVIDIA CUDA 13.0 Toolkit EULA](https://docs.nvidia.com/cuda/archive/13.0.0/eula/index.html), including its distribution terms and Attachment A.
- The Python runtime shipped with Control comes from the [Python Build Standalone 20261009 release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261009). The source and licenses for the build are available at [its 20261009 source tag](https://github.com/astral-sh/python-build-standalone/tree/20261009). See the `python-build-standalone/` directory for its notices.
- Python packages, the Outfit fonts, and KaTeX carry their licenses alongside the installed files. Python dependency metadata is in the respective `.dist-info/` directories.

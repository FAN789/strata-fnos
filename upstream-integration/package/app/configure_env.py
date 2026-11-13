import os
import sys

from service import APP, RUN, initialize, runtime_env

initialize()
os.chdir(RUN)
python = APP / "control/python/bin/python3"
os.execve(python, [str(python), "-B", str(APP / "configure_model.py"), *sys.argv[1:]], runtime_env())

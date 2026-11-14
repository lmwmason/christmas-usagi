"""CBGPU MCP v1.0.1 accepts at most 4 CPUs and 16g RAM; no GPU setting.

These are deployment-setting limits, not proof of account quota or host hardware.
"""
import os

CPU_THREADS = min(4,max(1,int(os.environ.get('USAGI_CPU_THREADS','4'))))
for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[name]='1'
os.environ['OMP_NUM_THREADS']=str(CPU_THREADS)
os.environ['NUMBA_NUM_THREADS']=str(CPU_THREADS)
TARGET_MEMORY = '16g'

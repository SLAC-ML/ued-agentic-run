# Environment for GPT (General Particle Tracer 3.43) + the analysis Python env on S3DF.
#   source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh
export AGENTIC_ROOT=/sdf/group/mli/zhezhang/ued/agentic
export GPT_HOME=$AGENTIC_ROOT/sw/gpt343-CentOS7-devtoolset8-1-apr-2021-avx2
export GPTLICENSE=1109314912
# GPT warns without this; idle OpenMP threads sleep instead of spinning (matters on shared nodes)
export OMP_WAIT_POLICY=PASSIVE
case ":$PATH:" in *":$GPT_HOME/bin:"*) ;; *) export PATH=$GPT_HOME/bin:$PATH ;; esac

# Analysis env: numpy/pandas/scipy/matplotlib/jupyter (built with `module load uv`)
if [ -f "$AGENTIC_ROOT/.venv/bin/activate" ]; then
    source "$AGENTIC_ROOT/.venv/bin/activate"
fi

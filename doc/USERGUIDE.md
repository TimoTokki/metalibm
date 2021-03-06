# Metalibm User Guide

## USAGE
Example of meta-functions can be found in the metalibm_functions directory.

### Generating a function

Example to generate a faithful (default) approximation of the exponential function for single precision and a x86 AVX2 target:
```python2 metalibm_functions/ml_exp.py --precision binary32 --target x86_avx2 --output x86_avx2_exp2d.c ```

### Generating a function and its functionnal test bench

The following command line will generate code for single precision exponential
 and a functionnal test bench with 1000 random inputs.

```python2 metalibm_functions/ml_exp.py --precision binary32 --auto-test 1000 --target x86 --output x86_exp2f.c ```

### Generating a function and its performance test bench

The following command line will generate code for single precision exponential
 and a performance test bench with 1000 random inputs (wrapped in an outer loop
 for better measurement stability).

```python2 metalibm_functions/ml_exp.py --precision binary32 --bench 1000 --target x86 --output x86_exp2f.c ```

Note: --bench and --auto-test options can be combined.

### Building a function after generation

To check that the generated code compiles correctly, use the **--build** option to trigger compiling after generating

```python2 metalibm_functions/ml_exp.py --precision binary32 --build --target x86 --output x86_exp2f.c ```

### executing a test bench

By adding **--execute** on the command line, metalibm will try to build and execute the generated file.
Beware, pure function code can not be executed (it is not a program simply a function), functionnal or performance testbench can be executed.

```python2 metalibm_functions/ml_exp.py --precision binary32 --auto-test -- execute --target x86 --output x86_exp2f.c ```


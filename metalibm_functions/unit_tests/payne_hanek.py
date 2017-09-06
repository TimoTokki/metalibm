
# -*- coding: utf-8 -*-

import sys

from sollya import S2, pi

from metalibm_core.core.ml_function import ML_Function, ML_FunctionBasis

from metalibm_core.core.attributes import ML_Debug
from metalibm_core.core.ml_operations import *
from metalibm_core.core.ml_formats import *
from metalibm_core.core.ml_complex_formats import *
from metalibm_core.core.polynomials import *
from metalibm_core.core.ml_table import ML_Table
from metalibm_core.core.payne_hanek import generate_payne_hanek

from metalibm_core.code_generation.c_code_generator import CCodeGenerator
from metalibm_core.code_generation.generic_processor import GenericProcessor
from metalibm_core.code_generation.mpfr_backend import MPFRProcessor


from metalibm_core.code_generation.gappa_code_generator import GappaCodeGenerator

from metalibm_core.utility.gappa_utils import execute_gappa_script_extract
from metalibm_core.utility.ml_template import *

from metalibm_core.utility.arg_utils import test_flag_option, extract_option_value

from metalibm_core.utility.debug_utils import *

class ML_UT_PayneHanek(ML_Function("ml_ut_payne_hanek")):
  def __init__(self,
                 arg_template,
                 ):
    #precision = ArgDefault.select_value([arg_template.precision, precision])
    #io_precisions = [precision] * 2

    # initializing base class
    ML_FunctionBasis.__init__(self,
      arg_template = arg_template
    )

    #self.precision = precision


  def generate_scheme(self):
    int_precision = {ML_Binary32 : ML_Int32, ML_Binary64 : ML_Int64}[self.precision]
    vx = self.implementation.add_input_variable("x", self.precision)
    k = 4
    frac_pi = S2**k/pi
    
    red_stat, red_vx, red_int = generate_payne_hanek(vx, frac_pi, self.precision, k = k, n= 100)
    C32 = Constant(32, precision = int_precision)
    red_int_f = Conversion(Select(red_int < Constant(0, precision = int_precision), red_int + C32, red_int), precision = self.precision)

    red_add = Addition(
      red_vx, 
      red_int_f,
      precision = self.precision
    )

    scheme = Statement(
      red_stat,
      Return(red_add, precision = self.precision)
    )

    return scheme

if __name__ == "__main__":
  # auto-test
  arg_template = ML_NewArgTemplate("new_ut_payne_hanek", default_output_file = "new_ut_payne_hanek.c" )
  args = arg_template.arg_extraction()


  ml_ut_payne_hanek = ML_UT_PayneHanek(args)

  ml_ut_payne_hanek.gen_implementation(display_after_gen = False, display_after_opt = False)

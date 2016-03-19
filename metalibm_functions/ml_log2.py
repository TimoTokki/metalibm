# -*- coding: utf-8 -*-

import sys

import sollya

from sollya import S2, Interval, ceil, floor, round, inf, sup, abs, log, exp, log2, guessdegree, x, RN, absolute 

from metalibm_core.core.ml_function import ML_Function, ML_FunctionBasis, DefaultArgTemplate

from metalibm_core.core.attributes import ML_Debug
from metalibm_core.core.ml_operations import *
from metalibm_core.core.ml_formats import *
from metalibm_core.core.ml_complex_formats import ML_Mpfr_t
from metalibm_core.core.polynomials import *
from metalibm_core.core.ml_table import ML_Table

from metalibm_core.code_generation.generic_processor import GenericProcessor
from metalibm_core.code_generation.gappa_code_generator import GappaCodeGenerator
from metalibm_core.code_generation.generator_utility import FunctionOperator, FO_Result, FO_Arg

from metalibm_core.utility.gappa_utils import execute_gappa_script_extract
from metalibm_core.utility.ml_template import *
from metalibm_core.utility.debug_utils import * 

class ML_Log2(ML_Function("ml_log2")):
  def __init__(self, 
                 arg_template = DefaultArgTemplate,
                 precision = ML_Binary32, 
                 abs_accuracy = S2**-24, 
                 libm_compliant = True, 
                 debug_flag = False, 
                 fuse_fma = True, 
                 fast_path_extract = True,
                 target = GenericProcessor(), 
                 output_file = "log2f.c", 
                 function_name = "log2f"):
    # extracting precision argument from command line
    precision = ArgDefault.select_value([arg_template.precision, precision])
    io_precisions = [precision] * 2

    # initializing base class
    ML_FunctionBasis.__init__(self, 
      base_name = "log2",
      function_name = function_name,
      output_file = output_file,

      io_precisions = io_precisions,
      abs_accuracy = None,
      libm_compliant = libm_compliant,

      processor = target,
      fuse_fma = fuse_fma,
      fast_path_extract = fast_path_extract,

      debug_flag = debug_flag,
      arg_template = arg_template
    )

    self.precision = precision


  def generate_emulate(self, result, mpfr_x, mpfr_rnd):
    """ generate the emulation code for ML_Log2 functions
        mpfr_x is a mpfr_t variable which should have the right precision
        mpfr_rnd is the rounding mode
    """
    #mpfr_x = emulate_implementation.add_input_variable("x", ML_Mpfr_t)
    #mpfr_rnd = emulate_implementation.add_input_variable("rnd", ML_Int32)
    emulate_func_name = "mpfr_log2"
    emulate_func_op = FunctionOperator(emulate_func_name, arg_map = {0: FO_Result(0), 1: FO_Arg(0), 2: FO_Arg(1)}, require_header = ["mpfr.h"]) 
    emulate_func   = FunctionObject(emulate_func_name, [ML_Mpfr_t, ML_Int32], ML_Mpfr_t, emulate_func_op)
    #emulate_func_op.declare_prototype = emulate_func
    mpfr_call = Statement(ReferenceAssign(result, emulate_func(mpfr_x, mpfr_rnd)))

    return mpfr_call


  def generate_scheme(self):
    vx = self.implementation.add_input_variable("x", self.get_input_precision()) 

    sollya_precision = self.get_input_precision().get_sollya_object()

    # local overloading of RaiseReturn operation
    def ExpRaiseReturn(*args, **kwords):
        kwords["arg_value"] = vx
        kwords["function_name"] = self.function_name
        return RaiseReturn(*args, **kwords)


    test_nan_or_inf = Test(vx, specifier = Test.IsInfOrNaN, likely = False, debug = True, tag = "nan_or_inf")
    test_nan = Test(vx, specifier = Test.IsNaN, debug = True, tag = "is_nan_test")
    test_positive = Comparison(vx, 0, specifier = Comparison.GreaterOrEqual, debug = True, tag = "inf_sign")

    test_signaling_nan = Test(vx, specifier = Test.IsSignalingNaN, debug = True, tag = "is_signaling_nan")
    return_snan = Statement(ExpRaiseReturn(ML_FPE_Invalid, return_value = FP_QNaN(ML_Binary32)))


    vx_exp  = ExponentExtraction(vx, tag = "vx_exp", debug = debugd)

    int_precision = ML_Int64 if self.precision is ML_Binary64 else ML_Int32

    # retrieving processor inverse approximation table
    dummy_var = Variable("dummy", precision = self.precision)
    dummy_div_seed = DivisionSeed(dummy_var, precision = self.precision)
    inv_approx_table = self.processor.get_recursive_implementation(dummy_div_seed, language = None, table_getter = lambda self: self.approx_table_map)

    # table creation
    table_index_size = 7
    log_table = ML_Table(dimensions = [2**table_index_size, 2], storage_precision = self.precision, tag = self.uniquify_name("inv_table"))
    log_table[0][0] = 0.0
    log_table[0][1] = 0.0
    for i in xrange(1, 2**table_index_size):
        #inv_value = (1.0 + (self.processor.inv_approx_table[i] / S2**9) + S2**-52) * S2**-1
        #inv_value = (1.0 + (inv_approx_table[i][0] / S2**9) ) * S2**-1
        #print inv_approx_table[i][0], inv_value
        inv_value = inv_approx_table[i][0]
        value_high = round(log2(inv_value), self.precision.get_field_size() - (self.precision.get_exponent_size() + 1), sollya.RN)
        value_low = round(log2(inv_value) - value_high, sollya_precision, sollya.RN)
        log_table[i][0] = value_high
        log_table[i][1] = value_low

    def compute_log(_vx, exp_corr_factor = None):
        _vx_mant = MantissaExtraction(_vx, tag = "_vx_mant", debug = debug_lftolx)
        _vx_exp  = ExponentExtraction(_vx, tag = "_vx_exp", debug = debugd)

        table_index = BitLogicAnd(BitLogicRightShift(TypeCast(_vx_mant, precision = int_precision, debug = debuglx), self.precision.get_field_size() - 7, debug = debuglx), 0x7f, tag = "table_index", debug = debuglld) 

        # argument reduction
        # TODO: detect if single operand inverse seed is supported by the targeted architecture
        pre_arg_red_index = TypeCast(BitLogicAnd(TypeCast(DivisionSeed(_vx_mant, precision = self.precision, tag = "seed", debug = debug_lftolx, silent = True), precision = ML_UInt64), Constant(-2, precision = ML_UInt64), precision = ML_UInt64), precision = self.precision, tag = "pre_arg_red_index", debug = debug_lftolx)
        arg_red_index = Select(Equal(table_index, 0), 1.0, pre_arg_red_index, tag = "arg_red_index", debug = debug_lftolx)
        #if not processor.is_supported_operation(arg_red_index):
        #    if self.precision != ML_Binary32:
        #        arg_red_index = DivisionSeed(Conversion(_vx_mant, precision = ML_Binary32), precision = ML_Binary32,  
        _red_vx        = arg_red_index * _vx_mant - 1.0
        _red_vx.set_attributes(tag = "_red_vx", debug = debug_lftolx)
        inv_err = S2**-7
        red_interval = Interval(1 - inv_err, 1 + inv_err)

        # return in case of standard (non-special) input
        _log_inv_lo = TableLoad(log_table, table_index, 1, tag = "log_inv_lo", debug = debug_lftolx) 
        _log_inv_hi = TableLoad(log_table, table_index, 0, tag = "log_inv_hi", debug = debug_lftolx)

        print "building mathematical polynomial"
        approx_interval = Interval(-inv_err, inv_err)
        poly_degree = sup(guessdegree(log2(1+sollya.x)/sollya.x, approx_interval, S2**-(self.precision.get_field_size()+1))) + 1
        global_poly_object = Polynomial.build_from_approximation(log2(1+sollya.x)/sollya.x, poly_degree, [self.precision]*(poly_degree+1), approx_interval, sollya.absolute)
        poly_object = global_poly_object.sub_poly(start_index = 0)

        Attributes.set_default_silent(True)
        Attributes.set_default_rounding_mode(ML_RoundToNearest)

        print "generating polynomial evaluation scheme"
        _poly = PolynomialSchemeEvaluator.generate_horner_scheme(poly_object, _red_vx, unified_precision = self.precision)
        _poly.set_attributes(tag = "poly", debug = debug_lftolx)
        print "sollya global_poly_object"
        print global_poly_object.get_sollya_object()
        print "sollya poly_object"
        print poly_object.get_sollya_object()

        corr_exp = _vx_exp if exp_corr_factor == None else _vx_exp + exp_corr_factor
        split_red_vx = Split(_red_vx, precision = ML_DoubleDouble, tag = "split_red_vx", debug = debug_ddtolx) 
        red_vx_hi = split_red_vx.hi
        red_vx_lo = split_red_vx.lo

        Attributes.unset_default_rounding_mode()
        Attributes.unset_default_silent()

        # result = _red_vx * poly - log_inv_hi - log_inv_lo + _vx_exp * log2_hi + _vx_exp * log2_lo
        #pre_result = -_log_inv_hi + (_red_vx + (_red_vx * _poly + (- _log_inv_lo)))
        pre_result = -_log_inv_hi + (_red_vx * _poly + (- _log_inv_lo))
        pre_result.set_attributes(tag = "pre_result", debug = debug_lftolx)
        exact_log2_hi_exp = corr_exp 
        exact_log2_hi_exp.set_attributes(tag = "exact_log2_hi_hex", debug = debug_lftolx)
        _result = corr_exp + pre_result
        return _result, _poly, _log_inv_lo, _log_inv_hi, _red_vx

    result, poly, log_inv_lo, log_inv_hi, red_vx = compute_log(vx)
    result.set_attributes(tag = "result", debug = debug_lftolx)

    neg_input = Comparison(vx, 0, likely = False, specifier = Comparison.Less, debug = debugd, tag = "neg_input")
    vx_nan_or_inf = Test(vx, specifier = Test.IsInfOrNaN, likely = False, debug = debugd, tag = "nan_or_inf")
    vx_snan = Test(vx, specifier = Test.IsSignalingNaN, likely = False, debug = debugd, tag = "snan")
    vx_inf  = Test(vx, specifier = Test.IsInfty, likely = False, debug = debugd, tag = "inf")
    vx_subnormal = Test(vx, specifier = Test.IsSubnormal, likely = False, debug = debugd, tag = "vx_subnormal")
    vx_zero = Test(vx, specifier = Test.IsZero, likely = False, debug = debugd, tag = "vx_zero")

    exp_mone = Equal(vx_exp, -1, tag = "exp_minus_one", debug = debugd, likely = False)
    vx_one = Equal(vx, 1.0, tag = "vx_one", likely = False, debug = debugd)

    # exp=-1 case
    print "managing exp=-1 case"
    #red_vx_2 = arg_red_index * vx_mant * 0.5
    #approx_interval2 = Interval(0.5 - inv_err, 0.5 + inv_err)
    #poly_degree2 = sup(guessdegree(log(x), approx_interval2, S2**-(self.precision.get_field_size()+1))) + 1
    #poly_object2 = Polynomial.build_from_approximation(log(sollya.x), poly_degree, [self.precision]*(poly_degree+1), approx_interval2, sollya.absolute)
    #print "poly_object2: ", poly_object2.get_sollya_object()
    #poly2 = PolynomialSchemeEvaluator.generate_horner_scheme(poly_object2, red_vx_2, unified_precision = self.precision)
    #poly2.set_attributes(tag = "poly2", debug = debug_lftolx)
    #result2 = (poly2 - log_inv_hi - log_inv_lo)

    result2 = (-log_inv_hi - 1.0) + ((poly * red_vx) - log_inv_lo)
    result2.set_attributes(tag = "result2", debug = debug_lftolx)

    m100 = -100
    S2100 = Constant(S2**100, precision = self.precision)
    result_subnormal, _, _, _, _ = compute_log(vx * S2100, exp_corr_factor = m100)
    result_subnormal.set_attributes(tag = "result_subnormal", debug = debug_lftolx)

    print "managing close to 1.0 cases"
    one_err = S2**-7
    approx_interval_one = Interval(-one_err, one_err)
    red_vx_one = vx - 1.0
    poly_degree_one = sup(guessdegree(log(1+x)/x, approx_interval_one, S2**-(self.precision.get_field_size()+1))) + 1
    poly_object_one = Polynomial.build_from_approximation(log(1+sollya.x)/sollya.x, poly_degree_one, [self.precision]*(poly_degree_one+1), approx_interval_one, absolute).sub_poly(start_index = 1)
    poly_one = PolynomialSchemeEvaluator.generate_horner_scheme(poly_object_one, red_vx_one, unified_precision = self.precision)
    poly_one.set_attributes(tag = "poly_one", debug = debug_lftolx)
    result_one = red_vx_one + red_vx_one * poly_one
    cond_one = (vx < (1+one_err)) & (vx > (1 - one_err))
    cond_one.set_attributes(tag = "cond_one", debug = debugd, likely = False)


    # main scheme
    print "MDL scheme"
    pre_scheme = ConditionBlock(neg_input,
        Statement(
            ClearException(),
            Raise(ML_FPE_Invalid),
            Return(FP_QNaN(self.precision))
        ),
        ConditionBlock(vx_nan_or_inf,
            ConditionBlock(vx_inf,
                Statement(
                    ClearException(),
                    Return(FP_PlusInfty(self.precision)),
                ),
                Statement(
                    ClearException(),
                    ConditionBlock(vx_snan,
                        Raise(ML_FPE_Invalid)
                    ),
                    Return(FP_QNaN(self.precision))
                )
            ),
            ConditionBlock(vx_subnormal,
                ConditionBlock(vx_zero, 
                    Statement(
                        ClearException(),
                        Raise(ML_FPE_DivideByZero),
                        Return(FP_MinusInfty(self.precision)),
                    ),
                    Statement(
                        ClearException(),
                        result_subnormal,
                        Return(result_subnormal)
                    )
                ),
                ConditionBlock(vx_one,
                    Statement(
                        ClearException(),
                        Return(FP_PlusZero(self.precision)),
                    ),
                    ConditionBlock(exp_mone,
                        Return(result2),
                        Return(result)
                    )
                    #ConditionBlock(cond_one,
                        #Return(new_result_one),
                        #ConditionBlock(exp_mone,
                            #Return(result2),
                            #Return(result)
                        #)
                    #)
                )
            )
        )
    )
    scheme = Statement(result, pre_scheme)
    return scheme


  def numeric_emulate(self, input_value):
    return log2(input_value)



if __name__ == "__main__":
  # auto-test
  arg_template = ML_NewArgTemplate(default_function_name = "new_log2", default_output_file = "new_log2.c" )
  args = arg_template.arg_extraction()


  ml_log2          = ML_Log2(args)
  ml_log2.gen_implementation()


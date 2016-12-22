# -*- coding: utf-8 -*-

import sys

import sollya

from sollya import S2, Interval, ceil, floor, round, inf, sup, log, exp, expm1, log2, guessdegree, dirtyinfnorm, RN, RD, cbrt
from sollya import parse as sollya_parse

from metalibm_core.core.attributes import ML_Debug
from metalibm_core.core.ml_operations import *
from metalibm_core.core.ml_formats import *
from metalibm_core.core.ml_table import ML_Table
from metalibm_core.code_generation.vhdl_backend import VHDLBackend
from metalibm_core.core.polynomials import *
from metalibm_core.core.ml_entity import ML_Entity, ML_EntityBasis, DefaultEntityArgTemplate
from metalibm_core.code_generation.generator_utility import FunctionOperator, FO_Result, FO_Arg


from metalibm_core.utility.ml_template import *
from metalibm_core.utility.log_report  import Log
from metalibm_core.utility.debug_utils import *
from metalibm_core.utility.num_utils   import ulp
from metalibm_core.utility.gappa_utils import is_gappa_installed


from metalibm_core.core.ml_hdl_format import *
from metalibm_core.core.ml_hdl_operations import *




class FP_Adder(ML_Entity("fp_adder")):
  def __init__(self, 
             arg_template = DefaultEntityArgTemplate, 
             precision = ML_Binary32, 
             accuracy  = ML_Faithful,
             libm_compliant = True, 
             debug_flag = False, 
             fuse_fma = True, 
             fast_path_extract = True,
             target = VHDLBackend(), 
             output_file = "fp_adder.vhd", 
             entity_name = "fp_adder",
             language = VHDL_Code,
             vector_size = 1):
    # initializing I/O precision
    precision = ArgDefault.select_value([arg_template.precision, precision])
    io_precisions = [precision] * 2

    # initializing base class
    ML_EntityBasis.__init__(self, 
      base_name = "fp_adder",
      entity_name = entity_name,
      output_file = output_file,

      io_precisions = io_precisions,
      abs_accuracy = None,

      backend = target,
      fuse_fma = fuse_fma,
      fast_path_extract = fast_path_extract,

      debug_flag = debug_flag,
      language = language,
      arg_template = arg_template
    )

    self.accuracy  = accuracy
    self.precision = precision

  def generate_scheme(self):
    io_precision = VirtualFormat(base_format = self.precision, support_format = ML_StdLogicVectorFormat(self.precision.get_bit_size()))
    # declaring standard clock and reset input signal
    clk = self.implementation.add_input_signal("clk", ML_StdLogic)
    reset = self.implementation.add_input_signal("reset", ML_StdLogic)
    # declaring main input variable
    vx = self.implementation.add_input_signal("x", io_precision) 
    vy = self.implementation.add_input_signal("y", io_precision) 

    # vx must be aligned with vy
    # the largest shit amount (in absolute value) is precision + 2
    # (1 guard bit and 1 rounding bit)
    exp_precision     = ML_StdLogicVectorFormat(self.precision.get_exponent_size())
    exp_precision_ext = ML_StdLogicVectorFormat(self.precision.get_exponent_size() + 1)

    mant_precision    = ML_StdLogicVectorFormat(self.precision.get_field_size())

    mant_vx = MantissaExtraction(vx, precision = mant_precision)
    mant_vy = MantissaExtraction(vy, precision = mant_precision)
    

    exp_vx = ExponentExtraction(vx, precision = exp_precision)
    exp_vy = ExponentExtraction(vy, precision = exp_precision)

    sign_vx = CopySign(vx, precision = ML_StdLogic)
    sign_vy = CopySign(vy, precision = ML_StdLogic)

    # determining if the operation is an addition (effective_op = '0')
    # or a subtraction (effective_op = '1')
    effective_op = BitLogicXor(sign_vx, sign_vy, precision = ML_StdLogic)

    ## Wrapper for zero extension
    # @param op the input operation tree
    # @param s integer size of the extension
    # @return the Zero extended operation node
    def zext(op,s):
      op_size = op.get_precision().get_bit_size() 
      ext_precision  = ML_StdLogicVectorFormat(op_size + s)
      return ZeroExt(op, s, precision = ext_precision)
    ## Generate the right zero extended output from @p optree
    def rzext(optree, ext_size):
      op_size = optree.get_precision().get_bit_size()
      ext_format = ML_StdLogicVectorFormat(ext_size)
      out_format = ML_StdLogicVectorFormat(op_size + ext_size)
      return Concatenation(optree, Constant(0, precision = ext_format), precision = out_format)

    exp_bias = self.precision.get_field_size() - 1

    exp_diff = Subtraction(
                Addition(
                  zext(exp_vx, 1), 
                  Constant(exp_bias, precision = exp_precision_ext),
                  precision = exp_precision_ext
                ),
                zext(exp_vy, 1), precision = exp_precision_ext)
    exp_diff_lt_0 = Comparison(exp_diff, Constant(0, precision = exp_precision_ext), specifier = Comparison.Less, precision = ML_Bool)
    exp_diff_gt_2bias = Comparison(exp_diff, Constant(2*exp_bias, precision = exp_precision_ext), specifier = Comparison.Greater, precision = ML_Bool)

    shift_amount_prec = ML_StdLogicVectorFormat(int(log2(2*exp_bias)))

    mant_shift = Select(
      exp_diff_lt_0,
      Constant(0, precision = shift_amount_prec),
      Select(
        exp_diff_gt_2bias,
        Constant(2*exp_bias, precision = shift_amount_prec),
        Truncate(exp_diff, precision = shift_amount_prec),
        precision = shift_amount_prec
      ),
      precision = shift_amount_prec
    )

    mant_ext_size = self.precision.get_field_size()
    shift_prec = ML_StdLogicVectorFormat(self.precision.get_field_size() * 2)
    shifted_mant_vy = BitLogicRightShift(rzext(mant_vy, mant_ext_size), mant_shift, precision = shift_prec)
    mant_vx_rext = rzext(mant_vx, mant_ext_size)

    mant_add = Addition(
                shifted_mant_vy, mant_vx_rext,
                precision = shift_prec)

    res_sign = CopySign(mant_add, precision = ML_StdLogic) 

    lzc_prec = shift_amount_prec
    add_lzc = CountLeadingZeros(mant_add, precision = lzc_prec)
    norm_add = BitLogicLeftShift(mant_add, add_lzc, precision = shift_prec)

    res_exp = Addition(
                add_lzc, 
                Addition(
                  exp_vx,
                  Constant(-2*exp_bias, precision = shift_amount_prec),
                  precision = shift_amount_prec
                ),
                precision = shift_amount_prec
              )

    vr_out = FloatBuild(res_sign, res_exp, mant_add, precision = self.precision)


    self.implementation.add_output_signal("vr_out", vr_out)

    #exp_vx = SignExtenstion(vx, exp_precision_ext)
    #exp_vy = SignExtenstion(vy, exp_precision_ext)

    #exp_diff = Subtraction(exp_vx, exp_vy, precision = exp_precision_ext)
    #exp_diff = Addition(exp_diff, Constant(shift_bias, precision = exp_precision_ext), precision = exp_precision_ext)


    #mant_precision = ML_StdLogicVectorFormat(self.precision.get_field_size())
    #mant_vx = MantissaExtraction(vx, precision = mant_precision)
    #mant_vy = MantissaExtraction(vy, precision = mant_precision)

    #mant_ext_precision = ML_StdLogicVectorFormat(self.precision.get_field_size() + shift_amount)
    #mant_vx = ZeroExtenstion
    #Shift(vx, exp_diff, 

    #self.implementation.start_new_stage()

    #shifted_mant = LogicalShift(mant_vy, exp_diff, precision = shift_precision)



    #vr_add = Addition(vx, vy, tag = "vr", precision = precision)
    #vr_sub = Subtraction(vx, vy, tag = "vr_sub", precision = precision)

    #self.implementation.start_new_stage()

    #vr_out = Select(
      #Comparison(exp_vx, exp_vy, precision = ML_Bool, specifier = Comparison.Greater),
      #vr_add,
      #Select(
        #Comparison(vx, Constant(1, precision = precision), precision = ML_Bool, specifier = Comparison.LessOrEqual),
        #vr_sub,
        #vx,
        #precision = precision
      #),
      #precision = precision,
      #tag = "vr_res"
    #)

    #for sig in [vx, vy, vr_add, vr_sub, vr_out]:
    #  print "%s, stage=%d" % (sig.get_tag(), sig.attributes.init_stage)

    #vr_d = Signal("vr_d", precision = vr.get_precision())

    #process_statement = Statement(
    #  ConditionBlock(LogicalAnd(Event(clk, precision = ML_Bool), Comparison(clk, Constant(1, precision = ML_StdLogic), specifier = Comparison.Equal, precision = ML_Bool), precision = ML_Bool), ReferenceAssign(vr_d, vr))
    #)
    #process = Process(process_statement, sensibility_list = [clk, reset])
    #self.implementation.add_process(process)

    #self.implementation.add_output_signal("r_d", vr_d)
    #self.implementation.add_output_signal("r", vr)
    #self.implementation.add_output_signal("vr_out", vr_out)

    return [self.implementation]

  standard_test_cases =[sollya_parse(x) for x in  ["1.1", "1.5"]]


if __name__ == "__main__":
    # auto-test
    arg_template = ML_EntityArgTemplate(default_entity_name = "new_fp_adder", default_output_file = "ml_fp_adder.vhd" )
    # argument extraction 
    args = parse_arg_index_list = arg_template.arg_extraction()

    ml_hw_adder      = FP_Adder(args)

    ml_hw_adder.gen_implementation()

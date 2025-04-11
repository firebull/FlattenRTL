import copy
import re

from dataclasses import dataclass
from enum import Enum, EnumMeta
from typing import Any, Dict, List, Optional, Tuple

from rich import print

from antlr4.tree.Tree import TerminalNodeImpl
from antlr4_systemverilog.systemverilog import SystemVerilogParser, SystemVerilogParserVisitor

from design_parser import parse_design_to_tree, extract_module, replace_module, extract_modules

from progress.bar import FillingSquaresBar


class SignalDirection(Enum):
    INPUT = 1
    OUTPUT = 2
    INOUT = 3


class SignalTypeMeta(EnumMeta):
    def __call__(cls, value, *args, **kwargs):
        if isinstance(value, str):
            for member in cls:
                if member.name.lower() == value.lower():
                    return member
            raise ValueError(f"{value} is not a valid {cls.__name__}")
        return super().__call__(value, *args, **kwargs)


class SignalType(Enum, metaclass=SignalTypeMeta):
    UNSET = 0
    WIRE = 1
    REG = 2
    INTEGER = 3
    REAL = 4
    TIME = 5
    REALTIME = 6
    LOGIC = 7
    BIT = 8
    BYTE = 9
    SHORTINT = 10
    INT = 11
    LONGINT = 12
    SHORTREAL = 13

    def __str__(self) -> str:
        return self.name.lower()


def add_txt_to_list(lst: List[str], text: str, prefix: str = "") -> None:
    """
    This function is used to add the text to the list inplace
    It will split the text by lines and add each line to the list.
    Also it will split by ";" and add each part to the list.
    It will also add the prefix to each part.

    :param lst: The list to add the text to.
    :param text: The text to add to the list.
    :param prefix: The prefix to add to the text.

    :return: None
    """
    for line in text.splitlines():
        line = line.rstrip()

        if line:
            parts = line.split(";")
            for i, part in enumerate(parts):
                stripped = part.rstrip()
                if stripped:
                    if i < len(parts) - 1:
                        lst.append(prefix + stripped + ";")
                    else:
                        lst.append(prefix + stripped)
        else:
            lst.append("")


@dataclass
class TopModuleNodeFinder(SystemVerilogParserVisitor):
    """
    This class is used to find the top module node in the tree.

    :param top_module: The name of the top module.
    """

    top_module: str

    def __post_init__(self):
        self.top_module_node = None

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        module_name = ctx.module_header().module_identifier().getText()
        if module_name == self.top_module:
            self.top_module_node = ctx


class MyModuleInstantiationVisitor(SystemVerilogParserVisitor):
    def __init__(self, exclude_module):
        self.is_first_instantiation_module = False
        self.module_identifier_dict = {}
        self.module_param = []
        self.name_of_module_instances = []
        self.list_of_ports_rhs = []
        self.dict_of_lhs_to_rhs = {}
        self.list_of_ports_rhs_width = []
        self.dict_of_parameters = {}

        self.exclude_module = exclude_module

    def visitModule_program_interface_instantiation(
        self, ctx: SystemVerilogParser.Module_program_interface_instantiationContext
    ):
        if (
            ctx.instance_identifier().getText() not in self.exclude_module and not self.is_first_instantiation_module
            # or self.module_identifier == ctx.instance_identifier().getText()
        ):
            # self.is_first_instantiation_module = True
            self.first_instantiation = ctx
            if ctx.instance_identifier().getText() not in self.module_identifier_dict:
                self.module_identifier_dict[ctx.instance_identifier().getText()] = []

            for i in range(0, len(ctx.hierarchical_instance())):
                self.name_of_module_instances.append(ctx.hierarchical_instance()[i].name_of_instance().getText())
                self.module_identifier_dict[ctx.instance_identifier().getText()].append(
                    self.name_of_module_instances[-1]
                )
                # get ports_connnections
                ports_connections = ctx.hierarchical_instance()[i].list_of_port_connections()

                for child in ports_connections.getChildren():
                    if isinstance(child, TerminalNodeImpl):
                        pass
                    else:
                        if hasattr(child, "port_assign") and child.port_assign().expression() is not None:
                            self.list_of_ports_rhs.append(child.port_assign().expression().getText())
                        elif isinstance(child, SystemVerilogParser.Ordered_port_connectionContext):
                            self.list_of_ports_rhs.append(child.getText())
                        else:
                            self.list_of_ports_rhs.append("")

                        if isinstance(child, SystemVerilogParser.Ordered_port_connectionContext):
                            if self.dict_of_lhs_to_rhs.get(self.name_of_module_instances[-1]) is None:
                                self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]] = []
                            self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]].append(child.getText())
                        elif isinstance(child, SystemVerilogParser.Named_port_connectionContext) is not None:
                            if self.dict_of_lhs_to_rhs.get(self.name_of_module_instances[-1]) is None:
                                self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]] = {}

                            child_port_id = child.port_identifier().getText()

                            if child.port_assign() is not None:
                                if child.port_assign().expression() is not None:
                                    self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]][child_port_id] = (
                                        child.port_assign().expression().getText()
                                    )
                                    self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]][child_port_id] = (
                                        self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]][
                                            child_port_id
                                        ].replace("?", " ? ")
                                    )
                                else:
                                    self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]][child_port_id] = ""
                            else:
                                self.dict_of_lhs_to_rhs[self.name_of_module_instances[-1]][child_port_id] = ""

                        if ctx.parameter_value_assignment() is not None:
                            list_of_parameter_assignments = (
                                ctx.parameter_value_assignment().list_of_parameter_assignments()
                            )
                            for child in list_of_parameter_assignments.getChildren():
                                if isinstance(child, TerminalNodeImpl):
                                    pass
                                else:
                                    if isinstance(child, SystemVerilogParser.Named_parameter_assignmentContext):
                                        if self.dict_of_parameters.get(self.name_of_module_instances[-1]) is None:
                                            self.dict_of_parameters[self.name_of_module_instances[-1]] = {}
                                        self.dict_of_parameters[self.name_of_module_instances[-1]][
                                            self.name_of_module_instances[-1]
                                            + "___"
                                            + child.parameter_identifier().getText()
                                        ] = child.param_expression().getText()
                                    elif isinstance(child, SystemVerilogParser.Ordered_parameter_assignmentContext):
                                        if self.dict_of_parameters.get(self.name_of_module_instances[-1]) is None:
                                            self.dict_of_parameters[self.name_of_module_instances[-1]] = {}
                                        self.dict_of_parameters[self.name_of_module_instances[-1]][
                                            int(list_of_parameter_assignments.children.index(child) / 2)
                                        ] = child.getText()


class ParamVisitor(SystemVerilogParserVisitor):
    def __init__(self, cur_dict_of_parameters, cur_prefixs):
        self.counter = 0
        self.cur_prefixs = cur_prefixs
        self.cur_dict_of_parameters = cur_dict_of_parameters

    def is_parents_parameter_port_list(self, ctx):
        if ctx is None:
            return False
        if not isinstance(ctx, SystemVerilogParser.Parameter_port_listContext):
            return self.is_parents_parameter_port_list(ctx.parentCtx)
        else:
            return True

    # A very special case:
    # "Parameter A = 3"
    # "Parameter B = A;"
    # After flatten, it should be
    # Parameter B = [cur_prefix]_A;
    # Can even handle complicated case like:
    # Parameter C = A + B;
    def find_and_repalce_param_in_param_value(self, param_value, prefix, cur_dict_of_parameter):
        item = cur_dict_of_parameter[prefix]
        for _key in item.keys():
            if isinstance(_key, int):
                continue

            tmp_item = _key[len(prefix) + 1 :]
            # Find whole word 'item' in param_value
            pattern = r"\b{}\b".format(tmp_item)

            if re.search(pattern, param_value):
                if prefix + "_" + tmp_item in item:
                    param_value = re.sub(pattern, _key, param_value)

        return param_value

    # assign to cur_dict_of_parameters
    def visitParam_assignment(self, ctx: SystemVerilogParser.Param_assignmentContext):
        # Whether current parameter assignment is under module header, if not, we should not collect it
        # module xxx();
        # parameter xxx; <- would not affect the header
        if not self.is_parents_parameter_port_list(ctx):
            return

        if ctx.getChildCount() == 3:
            param_name = ctx.getChild(0).getText().replace(" ", "")
            param_value = ctx.getChild(2).getText().replace(" ", "")

            for item in self.cur_prefixs:
                if self.cur_dict_of_parameters.get(item) is None:
                    self.cur_dict_of_parameters[item] = {}

                if self.cur_dict_of_parameters[item].get(item + "___" + param_name) is None:
                    # Handle the ordered parameter
                    if self.cur_dict_of_parameters[item].get(self.counter) is not None:
                        self.cur_dict_of_parameters[item][item + "___" + param_name] = self.cur_dict_of_parameters[
                            item
                        ].get(self.counter)
                    else:
                        param_value = self.find_and_repalce_param_in_param_value(
                            param_value, item, self.cur_dict_of_parameters
                        )
                        self.cur_dict_of_parameters[item][item + "___" + param_name] = param_value

            self.counter += 1


class OrderedModulePortVisitor(SystemVerilogParserVisitor):
    def __init__(self, dict_of_lhs_to_rhs, instance_name, cur_lhs):
        self.instance_name = instance_name
        self.dict_of_lhs_to_rhs = dict_of_lhs_to_rhs
        self.port_var_list = dict_of_lhs_to_rhs[instance_name]
        self.dict_of_lhs_to_rhs[self.instance_name] = {}
        self.index = 0
        self.cur_lhs = cur_lhs

    def visitList_of_port_declarations(self, ctx: SystemVerilogParser.List_of_port_declarationsContext):
        for item in ctx.port_decl():
            item_name = item.ansi_port_declaration().port_identifier().getText()
            self.dict_of_lhs_to_rhs[self.instance_name][item_name] = self.port_var_list[self.index]
            self.cur_lhs.append(item_name)
            self.index += 1

    # def visitPort_declaration(self, ctx:SystemVerilogParser.Port_declarationContext):
    #     if ctx.input_declaration() is not None:
    #         for i in range(0, len(ctx.input_declaration().list_of_port_identifiers().port_id())):
    #             self.dict_of_lhs_to_rhs[self.instance_name][ctx.input_declaration().list_of_port_identifiers().port_id()[i].getText()] = \
    #                 self.port_var_list[self.index]
    #             self.cur_lhs.append(ctx.input_declaration().list_of_port_identifiers().port_id()[i].getText())
    #             self.index += 1
    #     elif ctx.output_declaration() is not None:
    #         if ctx.output_declaration().list_of_port_identifiers() is not None:
    #             for i in range(0, len(ctx.output_declaration().list_of_port_identifiers().port_id())):
    #                 self.dict_of_lhs_to_rhs[self.instance_name][ctx.output_declaration().list_of_port_identifiers().port_id()[i].getText()] = \
    #                     self.port_var_list[self.index]
    #                 self.cur_lhs.append(ctx.output_declaration().list_of_port_identifiers().port_id()[i].getText())
    #                 self.index += 1
    #         elif ctx.output_declaration().list_of_variable_port_identifiers() is not None:
    #             for i in range(0, len(ctx.output_declaration().list_of_variable_port_identifiers().var_port_id())):
    #                 self.dict_of_lhs_to_rhs[self.instance_name][ctx.output_declaration().list_of_variable_port_identifiers().var_port_id()[i].getText()] = \
    #                     self.port_var_list[self.index]
    #                 self.cur_lhs.append(ctx.output_declaration().list_of_variable_port_identifiers().var_port_id()[i].getText())
    #                 self.index += 1


class MoudleParameterPortVisitor(SystemVerilogParserVisitor):
    def __init__(self, design, cur_identifier_dict, cur_prefixs, cur_dict_of_parameter, top_module):
        self.start = None
        self.stop = None
        self.ports_parameter = None
        self.design = design
        self.cur_identifier_dict = cur_identifier_dict
        self.cur_prefixs = cur_prefixs
        self.cur_dict_of_parameters = cur_dict_of_parameter

        self.top_module = top_module

    def _modify_port_parameter(self):
        ports_parameter = self.design[self.start : self.stop + 1]
        for item in self.cur_prefixs:
            if self.cur_dict_of_parameters.get(item) is None:
                continue
            else:
                # find index of the last ")" of str ports_parameter
                index = ports_parameter.rfind(")")
                index = index - len(ports_parameter)

                for key in self.cur_dict_of_parameters[item]:
                    # ignore the key with int type
                    if isinstance(key, int):
                        continue
                    ports_parameter = (
                        ports_parameter[:index]
                        + ",\nparameter "
                        + key
                        + "="
                        + self.cur_dict_of_parameters[item][key]
                        + ports_parameter[index:]
                    )
            self.ports_parameter = ports_parameter

    def _add_port_parameter(self):
        ports_parameter = " #()"
        for key in self.cur_identifier_dict:
            instance_list = self.cur_identifier_dict[key]

            for item in self.cur_prefixs:
                if item in instance_list:
                    if self.cur_dict_of_parameters.get(item) is None:
                        continue
                    else:
                        # find index of the last ")" of str ports_parameter
                        index = ports_parameter.rfind(")")
                        index = index - len(ports_parameter)

                        for key in self.cur_dict_of_parameters[item]:
                            # ignore the key with int type
                            if isinstance(key, int):
                                continue
                            ports_parameter = (
                                ports_parameter[:index]
                                + "\n    parameter "
                                + key
                                + "="
                                + self.cur_dict_of_parameters[item][key]
                                + ","
                                + ports_parameter[index:]
                            )

        ports_parameter = (
            ports_parameter[: ports_parameter.rfind(",")] + ports_parameter[ports_parameter.rfind(",") + 1 :]
        )
        self.ports_parameter = ports_parameter

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        if ctx.module_header().parameter_port_list() is not None:
            self.start = ctx.module_header().parameter_port_list().start.start
            self.stop = ctx.module_header().parameter_port_list().stop.stop
            # If the submodule have parameters, we should generate new parameters from the submodule
            if self.start != self.stop:
                self._modify_port_parameter()
        else:
            self.start = ctx.module_header().module_identifier().stop.stop + 1
            self.stop = ctx.module_header().module_identifier().stop.stop
            self._add_port_parameter()


@dataclass
class InstModuleVisitor(SystemVerilogParserVisitor):
    design: str
    cur_module_identifier_dict: Dict[str, List[str]]
    cur_dict_of_parameters: Dict[str, Any]
    cur_prefixs: List[str]
    top_module: str
    dict_of_lhs_to_rhs: Dict[str, Any]
    cur_lhs: List[str]

    def __post_init__(self):
        self.inst_module_nodes = []
        self.inst_module_designs = []
        self.starts = []
        self.stops = []
        self.starts_stops_dict = {}
        self.indent = 2
        self.parameter_strat = None
        self.parameter_stop = None
        self.ports_param_str = None

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        module_name = ctx.module_header().module_identifier().getText()
        if module_name in self.cur_module_identifier_dict:
            self.starts.append(ctx.start.start)
            self.stops.append(ctx.stop.stop)
            self.starts_stops_dict[module_name] = len(self.starts) - 1
            self.inst_module_nodes.append(ctx)
            self.inst_module_designs.append(self.design)
            paramVisitor = ParamVisitor(self.cur_dict_of_parameters, self.cur_prefixs)
            paramVisitor.visit(ctx)

            # Ordered port assign
            for key in self.dict_of_lhs_to_rhs.keys():
                if type(self.dict_of_lhs_to_rhs[key]) is list:
                    ordered_port_visitor = OrderedModulePortVisitor(self.dict_of_lhs_to_rhs, key, self.cur_lhs)
                    ordered_port_visitor.visit(ctx)

        if self.starts != [] and self.cur_dict_of_parameters != {}:
            if module_name == self.top_module:
                moduleParameterPortVisitor = MoudleParameterPortVisitor(
                    self.inst_module_designs,
                    self.cur_module_identifier_dict,
                    self.cur_prefixs,
                    self.cur_dict_of_parameters,
                    self.top_module,
                )
                moduleParameterPortVisitor.visit(ctx)
                self.ports_param_str = moduleParameterPortVisitor.ports_parameter
                self.parameter_start = moduleParameterPortVisitor.start
                self.parameter_stop = moduleParameterPortVisitor.stop


class RenameModuleVisitor(SystemVerilogParserVisitor):
    def __init__(self, cur_prefixs_index, cur_prefixs, cur_module_identifier_dict, cur_dict_lhs_to_rhs):
        self.inst_module_node = None
        self.inst_module_design = None
        self.start = None
        self.stop = None
        self.indent = 2
        self.cur_prefixs_index = cur_prefixs_index
        self.is_no_port_parameter = False
        self.port_parameter_flag = False
        self.cur_prefixs = cur_prefixs
        self.cur_module_identifier_dict = cur_module_identifier_dict
        self.cur_dict_lhs_to_rhs = cur_dict_lhs_to_rhs

        self.repeat_declr = set()

    def is_parents_parameter_port_list(self, ctx):
        if ctx is None:
            return False

        if not isinstance(ctx, SystemVerilogParser.Parameter_port_listContext):
            return self.is_parents_parameter_port_list(ctx.parentCtx)
        else:
            return True

    def is_parents_function_declaration(self, ctx):
        if ctx is None:
            return False

        if not isinstance(ctx, SystemVerilogParser.Function_declarationContext):
            return self.is_parents_function_declaration(ctx.parentCtx)
        else:
            return True

        "This function is used to traverse the tree and change the name of the instance"

    def _traverse_children(self, ctx):
        if self.is_parents_parameter_port_list(ctx):
            try:
                ctx.start.text = ""
                ctx.stop.text = ""
            except Exception:
                ctx.symbol.text = ""

        if isinstance(ctx, TerminalNodeImpl):
            if ctx.symbol.text == "?":
                ctx.symbol.text = " ? "
        else:
            for child in ctx.getChildren():
                if isinstance(child, SystemVerilogParser.Simple_identifierContext):
                    # TODO: Rewrite to match/case
                    if isinstance(
                        child.parentCtx.parentCtx,
                        SystemVerilogParser.Module_identifierContext,
                    ):
                        pass
                    elif isinstance(
                        child.parentCtx.parentCtx.parentCtx,
                        SystemVerilogParser.Module_program_interface_instantiationContext,
                    ):
                        pass
                    elif isinstance(
                        child.parentCtx.parentCtx,
                        SystemVerilogParser.Port_identifierContext,
                    ):
                        if self.is_parents_function_declaration(child):
                            child.start.text = (
                                "" + self.cur_prefixs[self.cur_prefixs_index] + "___" + child.start.text + ""
                            )
                        else:
                            pass
                    elif isinstance(
                        child.parentCtx.parentCtx,
                        SystemVerilogParser.Param_assignmentContext,
                    ) or isinstance(
                        child.parentCtx.parentCtx.parentCtx,
                        SystemVerilogParser.Named_parameter_assignmentContext,
                    ):
                        pass
                    elif isinstance(
                        child.parentCtx.parentCtx.parentCtx, SystemVerilogParser.Net_decl_assignmentContext
                    ) or isinstance(
                        child.parentCtx.parentCtx.parentCtx, SystemVerilogParser.Variable_decl_assignmentContext
                    ):
                        if child.start.text in self.cur_dict_lhs_to_rhs:
                            self.repeat_declr.add(child.start.text)
                        child.start.text = "" + self.cur_prefixs[self.cur_prefixs_index] + "___" + child.start.text + ""
                    else:
                        child.start.text = "" + self.cur_prefixs[self.cur_prefixs_index] + "___" + child.start.text + ""

                self._traverse_children(child)

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        module_name = ctx.module_header().module_identifier().getText()
        if module_name in self.cur_module_identifier_dict:
            self.start = ctx.start.start
            self.stop = ctx.stop.stop
            self.inst_module_node = ctx
            self._traverse_children(self.inst_module_node)


class InstModulePortVisitor(SystemVerilogParserVisitor):
    def __init__(self, cur_module_identifier_dict, cur_prefixs, cur_dict_of_parameters):
        self.inst_module_node = None
        self.is_first_instantiation_module = False
        self.list_of_ports_width = []
        self.list_of_ports_direction: List[SignalDirection] = []
        self.list_of_ports_type: List[SignalType] = []
        self.list_of_data_type = []
        self.list_of_ports_lhs = []
        self.cur_module_identifier_dict = cur_module_identifier_dict
        self.cur_prefixs = cur_prefixs
        self.cur_dict_of_parameters = cur_dict_of_parameters

    def _traverse_children_in_header(self, ctx):
        if isinstance(ctx, TerminalNodeImpl):
            if ctx.symbol.text == "?":
                ctx.symbol.text = " ? "
        else:
            for child in ctx.getChildren():
                child_type = child.getText()

                if isinstance(child, SystemVerilogParser.Port_directionContext) and child_type == "input":
                    if hasattr(child.parentCtx, "port_identifier"):
                        if child.parentCtx.port_identifier() is not None:
                            self.list_of_ports_lhs.append(child.parentCtx.port_identifier().getText())
                        else:
                            self.list_of_ports_lhs.append(child.list_of_variable_port_identifiers().getText())

                    self.list_of_ports_direction.append(SignalDirection.INPUT)
                    # self.list_of_ports_lhs.append(child.parentCtx.port_identifier().getText())
                    self.list_of_ports_type.append(SignalType.WIRE)

                    if (
                        hasattr(child.parentCtx, "implicit_data_type")
                        and child.parentCtx.implicit_data_type() is not None
                    ):
                        if child.parentCtx.implicit_data_type().packed_dimension() is not None:
                            self.list_of_ports_width.append(
                                child.parentCtx.implicit_data_type().packed_dimension()[0].getText()
                            )
                        else:
                            self.list_of_ports_width.append("")

                        if child.parentCtx.implicit_data_type().signing() is not None:
                            self.list_of_data_type.append(child.parentCtx.implicit_data_type().signing().getText())
                        else:
                            self.list_of_data_type.append("")
                    else:
                        self.list_of_ports_width.append("")
                        self.list_of_data_type.append("")

                    # TODO: data_type() is not none

                if isinstance(child, SystemVerilogParser.Port_directionContext) and child_type == "output":
                    self.list_of_ports_direction.append(SignalDirection.OUTPUT)

                    if child.parentCtx.data_type() is not None:
                        try:
                            sig_type = SignalType(child.parentCtx.data_type().integer_vector_type().getText())
                        except ValueError:
                            print(
                                f"[ERROR] Unknown signal type {child.parentCtx.data_type().integer_vector_type().getText()}"
                            )
                            sig_type = SignalType.UNSET

                        self.list_of_ports_type.append(sig_type)
                    else:
                        self.list_of_ports_type.append(SignalType.WIRE)

                    if child.parentCtx.port_identifier() is not None:
                        self.list_of_ports_lhs.append(child.parentCtx.port_identifier().getText())
                    else:
                        self.list_of_ports_lhs.append(child.list_of_variable_port_identifiers().getText())

                    if child.parentCtx.implicit_data_type():
                        if child.parentCtx.implicit_data_type().packed_dimension() is not None:
                            # TODO: Incorrect for multiple packed
                            self.list_of_ports_width.append(
                                child.parentCtx.implicit_data_type().packed_dimension()[0].getText()
                            )
                        else:
                            self.list_of_ports_width.append("")

                        if child.parentCtx.implicit_data_type().signing() is not None:
                            self.list_of_data_type.append(child.parentCtx.implicit_data_type().signing().getText())
                        else:
                            self.list_of_data_type.append("")
                    else:
                        self.list_of_ports_width.append("")
                        self.list_of_data_type.append("")
                    # TODO: data_type() is not none

                if isinstance(child, SystemVerilogParser.Inout_declarationContext) and child_type == "inout":
                    self.list_of_ports_direction.append(SignalDirection.INOUT)
                    self.list_of_ports_lhs.append(child.list_of_port_identifiers().getText())
                    self.list_of_ports_type.append(SignalType.WIRE)

                    if child.implicit_data_type() is not None:
                        if child.implicit_data_type().packed_dimension() is not None:
                            self.list_of_ports_width.append(child.implicit_data_type().packed_dimension()[0].getText())
                        else:
                            self.list_of_ports_width.append("")

                        if child.implicit_data_type().signing() is not None:
                            self.list_of_data_type.append(child.implicit_data_type().signing().getText())
                        else:
                            self.list_of_data_type.append("")
                    else:
                        self.list_of_ports_width.append("")
                        self.list_of_data_type.append("")

                if (
                    isinstance(child, SystemVerilogParser.Port_declContext)
                    and child.ansi_port_declaration().port_direction() is None
                ):
                    self.list_of_ports_direction.append(self.list_of_ports_direction[-1])
                    self.list_of_ports_lhs.append(child.ansi_port_declaration().port_identifier().getText())
                    self.list_of_ports_type.append(self.list_of_ports_type[-1])
                    self.list_of_ports_width.append(self.list_of_ports_width[-1])
                    self.list_of_data_type.append(self.list_of_data_type[-1])

                self._traverse_children_in_header(child)

    def _traverse_children_in_module_item(self, ctx):
        if isinstance(ctx, TerminalNodeImpl):
            if ctx.symbol.text == "?":
                ctx.symbol.text = " ? "
        else:
            for child in ctx.getChildren():
                child_0 = child.getChild(0)
                child_type = child_0.getText() if child_0 is not None else ""

                if isinstance(child, SystemVerilogParser.Input_declarationContext) and child_type == "input":
                    for item in child.list_of_port_identifiers().port_id():
                        self.list_of_ports_direction.append(SignalDirection.INPUT)
                        self.list_of_ports_lhs.append(item.getText())
                        self.list_of_ports_type.append(SignalType.WIRE)

                        if child.implicit_data_type() is not None:
                            if child.implicit_data_type().packed_dimension() is not None:
                                self.list_of_ports_width.append(
                                    child.implicit_data_type().packed_dimension()[0].getText()
                                )
                            else:
                                self.list_of_ports_width.append("")

                            if child.implicit_data_type().signing() is not None:
                                self.list_of_data_type.append(child.implicit_data_type().signing().getText())
                            else:
                                self.list_of_data_type.append("")
                        else:
                            self.list_of_ports_width.append("")
                            self.list_of_data_type.append("")

                if isinstance(child, SystemVerilogParser.Output_declarationContext) and child_type == "output":
                    if child.list_of_port_identifiers():
                        for item in child.list_of_port_identifiers().port_id():
                            self.list_of_ports_direction.append(SignalDirection.OUTPUT)
                            self.list_of_ports_lhs.append(item.getText())
                            self.list_of_ports_type.append(SignalType.WIRE)

                            if child.implicit_data_type() is not None:
                                if child.implicit_data_type().packed_dimension() is not None:
                                    self.list_of_ports_width.append(
                                        child.implicit_data_type().packed_dimension()[0].getText()
                                    )
                                else:
                                    self.list_of_ports_width.append("")

                                if child.implicit_data_type().signing() is not None:
                                    self.list_of_data_type.append(child.implicit_data_type().signing().getText())
                                else:
                                    self.list_of_data_type.append("")
                            else:
                                self.list_of_ports_width.append("")
                                self.list_of_data_type.append("")
                    elif child.list_of_variable_port_identifiers():
                        for item in child.list_of_variable_port_identifiers().var_port_id():
                            self.list_of_ports_direction.append(SignalDirection.OUTPUT)
                            self.list_of_ports_lhs.append(item.getText())
                            self.list_of_ports_type.append(SignalType.REG)

                            if child.data_type() is not None:
                                if child.data_type().packed_dimension() != []:
                                    self.list_of_ports_width.append(child.data_type().packed_dimension()[0].getText())
                                else:
                                    self.list_of_ports_width.append("")
                                if child.data_type().signing() is not None:
                                    self.list_of_data_type.append(child.data_type().signing().getText())
                                else:
                                    self.list_of_data_type.append("")
                            else:
                                self.list_of_ports_width.append("")
                                self.list_of_data_type.append("")

                # TODO: inout
                if isinstance(child, SystemVerilogParser.Inout_declarationContext) and child_type == "inout":
                    for item in child.list_of_port_identifiers().port_id():
                        self.list_of_ports_direction.append(SignalDirection.INOUT)
                        self.list_of_ports_lhs.append(item.getText())
                        self.list_of_ports_type.append(SignalType.WIRE)

                        if child.implicit_data_type() is not None:
                            if child.implicit_data_type().packed_dimension() is not None:
                                self.list_of_ports_width.append(
                                    child.implicit_data_type().packed_dimension()[0].getText()
                                )
                            else:
                                self.list_of_ports_width.append("")

                            if child.implicit_data_type().signing() is not None:
                                self.list_of_data_type.append(child.implicit_data_type().signing().getText())
                            else:
                                self.list_of_data_type.append("")
                        else:
                            self.list_of_ports_width.append("")
                            self.list_of_data_type.append("")

                if isinstance(child, SystemVerilogParser.Param_assignmentContext):
                    if child.getChildCount() == 3:
                        param_name = child.getChild(0).getText().replace(" ", "")
                        param_value = child.getChild(2).getText().replace(" ", "")

                        # Append param_name and param_value to cur_dict_of_parameters
                        for i in range(0, len(self.cur_prefixs)):
                            if self.cur_dict_of_parameters.get(self.cur_prefixs[i]) is None:
                                self.cur_dict_of_parameters[self.cur_prefixs[i]] = {}
                            if self.cur_dict_of_parameters[self.cur_prefixs[i]].get(
                                param_name
                            ) is None and param_name.startswith(self.cur_prefixs[i]):
                                self.cur_dict_of_parameters[self.cur_prefixs[i]][param_name] = param_value

                self._traverse_children_in_module_item(child)

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        def is_port_direction_under_module_header(ctx):
            module_header = ctx.module_header()
            list_of_port_declarations = module_header.list_of_port_declarations()

            if list_of_port_declarations is None:
                raise ValueError("No port declaration under module header")

            if (
                list_of_port_declarations.port_decl() != []
                and list_of_port_declarations.port_decl()[0].ansi_port_declaration().port_direction() is not None
            ):
                return True

            return False

        module_name = ctx.module_header().module_identifier().getText()
        if module_name in self.cur_module_identifier_dict:
            self.start = ctx.start.start
            self.stop = ctx.stop.stop
            self.inst_module_node = ctx
            # Whether the port direction under the module header
            if is_port_direction_under_module_header(ctx):
                self._traverse_children_in_header(self.inst_module_node)
            else:
                self._traverse_children_in_module_item(self.inst_module_node)


class InstBodyVisitor(SystemVerilogParserVisitor):
    def __init__(self):
        super().__init__()
        self.inst_module_node = None
        self.inst_module_design = None
        self.text = ""

    def formatProcess(self, ctx):
        self._traverse_children(ctx, 2)
        if ctx.getChildCount() == 0:
            return ""

        temp = "\n".join(child.getText() for child in ctx.getChildren()).replace(chr(31), "\n")

        new_strings = []
        add_txt_to_list(new_strings, temp)

        self.text = "\n".join(new_strings)

    def _traverse_children(self, ctx, indent=2):
        if isinstance(ctx, TerminalNodeImpl):
            pass
        else:
            for child in ctx.getChildren():
                # TODO: Rewrite to match/case
                match child:
                    case SystemVerilogParser.List_of_port_declarationsContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "

                    case SystemVerilogParser.Data_declarationContext() as data_decl:
                        match data_decl.data_type().getText():
                            case "reg":
                                child.start.text = chr(31) + " " * (indent - 2) + child.start.text
                            case "integer":
                                child.start.text = chr(31) + " " * (indent - 2) + child.start.text

                    case SystemVerilogParser.Net_declarationContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text

                    case SystemVerilogParser.Continuous_assignContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "

                    case SystemVerilogParser.Always_constructContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "
                        child.stop.text = child.stop.text + chr(31)

                    case SystemVerilogParser.Event_expressionContext():
                        child.start.text = " " + child.start.text + " "

                    case SystemVerilogParser.Case_statementContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "
                        child.stop.text = chr(31) + " " * (indent - 2) + child.stop.text + " "

                    case SystemVerilogParser.Case_itemContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "

                    case SystemVerilogParser.Conditional_statementContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "

                    case TerminalNodeImpl() if child.symbol.text == "else":
                        child.symbol.text = chr(31) + " " * (indent - 2) + child.symbol.text + " "
                    case TerminalNodeImpl() if child.symbol.text == "or":
                        child.symbol.text = " " * (indent - 2) + child.symbol.text + " "

                    case SystemVerilogParser.Simple_identifierContext():
                        child.start.text = " " + child.start.text + " "

                    case SystemVerilogParser.Nonblocking_assignmentContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "

                    case SystemVerilogParser.Seq_blockContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "
                        child.stop.text = chr(31) + " " * (indent - 2) + child.stop.text + " "

                    case SystemVerilogParser.Blocking_assignmentContext():
                        child.start.text = chr(31) + " " * (indent - 2) + child.start.text + " "

                    case SystemVerilogParser.Module_program_interface_instantiationContext():
                        child.start.text = chr(31) + " " * indent + child.start.text + " "

                    case SystemVerilogParser.Unary_operatorContext():
                        child.start.text = " " + child.start.text

                self._traverse_children(child, indent + 1)

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        self.inst_module_node = ctx
        self.formatProcess(self.inst_module_node)
        self.inst_module_node = parse_design_to_tree(self.text)


class InstBodyVisitor2(SystemVerilogParserVisitor):
    def __init__(self):
        self.start = None
        self.stop = None
        self.firstTerminal = False

    def ExtractStartAndStop(self, ctx):
        def is_port_direction_under_module_header(ctx):
            module_header = ctx.module_header()
            list_of_port_declarations = module_header.list_of_port_declarations()
            if list_of_port_declarations is None:
                raise ValueError("No port declaration under module header")

            if (
                list_of_port_declarations.port_decl() != []
                and list_of_port_declarations.port_decl()[0].ansi_port_declaration().port_direction() is not None
            ):
                return True
            return False

        self.stop = ctx.ENDMODULE().getSymbol().start - 1

        if is_port_direction_under_module_header(ctx):
            for child in ctx.module_header().getChildren():
                if isinstance(child, TerminalNodeImpl):
                    if not self.firstTerminal:
                        self.start = child.symbol.stop + 1
                        self.firstTerminal = True
        else:
            for child in ctx.module_item():
                child_txt = child.getText()

                if (
                    child_txt.startswith("input")
                    or child_txt.startswith("output")
                    or child_txt.startswith("inout")
                    or child_txt.startswith("parameter")
                ):
                    pass
                else:
                    self.start = child.start.start
                    break

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext):
        self.ExtractStartAndStop(ctx)


@dataclass
class IdentifierVisitor(SystemVerilogParserVisitor):
    cur_name_of_module_instance: List[str]
    top_module: str
    design: str
    cur_dict_of_parameters: Dict[str, Dict[str, str]]
    cur_new_variable: List[str]
    insert_parts: Dict[str, str]
    cur_new_assign: List[str]
    new_var_index: Dict[str, Tuple[int, int]]
    new_assign_index: Dict[str, Tuple[int, int]]

    def __post_init__(self):
        self.start = []
        self.stop = []
        self.tmp_design: List[str] = []

    def _traverse_children(self, ctx) -> None:
        if isinstance(ctx, TerminalNodeImpl):
            pass
        else:
            for child in ctx.getChildren():
                if isinstance(child, SystemVerilogParser.Module_program_interface_instantiationContext):
                    FIRST_HIER_INST = True
                    for cur_name in self.cur_name_of_module_instance:
                        # Handle multiple instance in one declaration
                        for i in range(0, len(child.children)):
                            if isinstance(child.getChild(i), SystemVerilogParser.Hierarchical_instanceContext):
                                if child.getChild(i).name_of_instance().getText() == cur_name:
                                    if FIRST_HIER_INST:
                                        self.start.append(child.getChild(0).start.start)
                                        FIRST_HIER_INST = False
                                    else:
                                        self.start.append(child.getChild(i).start.start)
                                    self.stop.append(child.getChild(i + 1).symbol.stop)

                self._traverse_children(child)

    def visitModule_declaration(self, ctx: SystemVerilogParser.Module_declarationContext) -> None:
        def remove_leading_whitespace(input_string) -> str:
            cleaned_string = re.sub(r"^\s*\n", "", input_string, flags=re.MULTILINE).lstrip()
            return cleaned_string

        if ctx.module_header().module_identifier().getText() == self.top_module:
            self._traverse_children(ctx)
            self.tmp_design.extend(self.design[: self.start[0]].splitlines())

            if self.cur_dict_of_parameters != {}:
                self.tmp_design.append("")

                for key, params in self.cur_dict_of_parameters.items():
                    self.tmp_design.append(f"  // PARAMETERS FOR: [{key}] MODULE")
                    for param_name, param_value in params.items():
                        self.tmp_design.append(" " * 2 + "parameter " + param_name + " = " + param_value + ";")

                    self.tmp_design.append("")

            keys = list(self.new_var_index.keys())
            key_0 = keys[0]
            self.tmp_design.append(f"  // INSTANCE: [{key_0}]")
            index_0_left = self.new_var_index[key_0][0]
            index_0_right = self.new_var_index[key_0][1]

            for i in range(index_0_left, index_0_right):
                if not self.tmp_design[-1][-3:].isspace():
                    self.tmp_design.append(2 * " " + self.cur_new_variable[i])
                else:
                    self.tmp_design.append(2 * " " + self.cur_new_variable[i])

            self.tmp_design.append("")

            for i in range(self.new_assign_index[key_0][0], self.new_assign_index[key_0][1]):
                self.tmp_design.append(" " * 2 + self.cur_new_assign[i])

            self.tmp_design.append("")

            add_txt_to_list(self.tmp_design, remove_leading_whitespace(self.insert_parts[key_0]), 2 * " ")
            self.tmp_design.append("")

            for i in range(1, len(self.start)):
                key_i = keys[i]
                index_left = self.new_var_index[key_i][0]
                index_right = self.new_var_index[key_i][1]
                substring = self.design[self.stop[i - 1] + 1 : self.start[i]]

                if not substring.isspace():
                    add_txt_to_list(self.tmp_design, substring, 2 * " ")

                self.tmp_design.append("")
                self.tmp_design.append(f"  // INSTANCE: [{key_i}]")

                for j in range(index_left, index_right):
                    add_txt_to_list(self.tmp_design, self.cur_new_variable[j], 2 * " ")

                self.tmp_design.append("")

                for j in range(self.new_assign_index[key_i][0], self.new_assign_index[key_i][1]):
                    add_txt_to_list(self.tmp_design, self.cur_new_assign[j], 2 * " ")

                self.tmp_design.append("")

                add_txt_to_list(self.tmp_design, remove_leading_whitespace(self.insert_parts[key_i]), 2 * " ")
                self.tmp_design.append("")

            add_txt_to_list(self.tmp_design, " " * 2 + self.design[self.stop[-1] + 1 :])


def pyflattenverilog(design: str, top_module: str, exlude_module: set) -> Tuple[bool, str]:
    bar = FillingSquaresBar(
        "{:<20}".format("Top node: "),
        color="green",
        max=4,
        suffix="%(percent)d%% - %(elapsed)ds",
    )

    top_design_str = extract_module(design, top_module)
    bar.next()

    tree = parse_design_to_tree(top_design_str)
    bar.next()

    # Step 1. Find the top-level module node
    top_finder = TopModuleNodeFinder(top_module)
    top_finder.visit(tree)
    top_node_tree = top_finder.top_module_node
    bar.next()

    # Step 2. Collect instantiation information of the top-level node
    visitor = MyModuleInstantiationVisitor(exlude_module)
    visitor.visit(top_node_tree)
    cur_module_identifier_dict = visitor.module_identifier_dict
    cur_name_of_module_instances = visitor.name_of_module_instances
    cur_prefixs = cur_name_of_module_instances
    cur_list_of_ports_rhs = visitor.list_of_ports_rhs
    cur_dict_of_parameters = visitor.dict_of_parameters
    dict_of_lhs_to_rhs = visitor.dict_of_lhs_to_rhs
    bar.next()
    bar.finish()

    if cur_module_identifier_dict == {}:
        return True, top_design_str
    else:
        print(f"MODULE: {cur_module_identifier_dict}")

    bar = FillingSquaresBar(
        "{:<20}".format("Processing: "),
        color="green",
        max=13,
        suffix="%(percent)d%% - %(elapsed)ds",
    )

    # Step 3. Rename and replace instantiation parts
    instance_design_strs = extract_modules(design, cur_module_identifier_dict)
    top_instance_str = ""

    for instance_design_str in instance_design_strs:
        top_instance_str += instance_design_str + "\n"

    bar.next()

    top_instance_str += top_design_str
    tree = parse_design_to_tree(top_instance_str)
    bar.next()

    visitor = InstModuleVisitor(
        cur_module_identifier_dict=cur_module_identifier_dict,
        cur_dict_of_parameters=cur_dict_of_parameters,
        cur_prefixs=cur_prefixs,
        top_module=top_module,
        design=top_instance_str,
        dict_of_lhs_to_rhs=dict_of_lhs_to_rhs,
        cur_lhs=[],
    )
    visitor.visit(tree)
    bar.next()

    inst_module_designs_dict = {}

    for key in visitor.starts_stops_dict:
        index = visitor.starts_stops_dict[key]
        inst_module_designs_dict[key] = top_instance_str[visitor.starts[index] : visitor.stops[index] + 1]

    # inst_module_design = top_instance_str[visitor.start : visitor.stop + 1]
    # cur_list_of_ports_rhs = visitor.cur_rhs

    # Step 3.1. Replace module variables
    inst_module_design_trees = []
    inst_module_nodes = []
    if cur_dict_of_parameters != {}:
        visitor.visit(tree)
        # This can be optimized
        top_instance_str = (
            top_instance_str[: visitor.parameter_start]
            + visitor.ports_param_str
            + top_instance_str[visitor.parameter_stop + 1 :]
        )
    bar.next()

    tree = parse_design_to_tree(top_instance_str)
    bar.next()

    visitor = TopModuleNodeFinder(top_module)
    visitor.visit(tree)
    top_node_tree = visitor.top_module_node
    bar.next()

    # We should identify repeat decleration
    repeat_decl_dict = {}
    inst_module_design_trees_dict = {}
    for key in cur_module_identifier_dict:
        for k in range(0, len(cur_module_identifier_dict[key])):
            inst_module_design = inst_module_designs_dict[key]
            tmp_inst_module_design = parse_design_to_tree(inst_module_design)
            visitor = RenameModuleVisitor(
                k,
                cur_module_identifier_dict[key],
                cur_module_identifier_dict,
                dict_of_lhs_to_rhs[cur_module_identifier_dict[key][k]],
            )
            visitor.visit(tmp_inst_module_design)
            inst_module_design_trees.append(tmp_inst_module_design)
            inst_module_nodes.append(visitor.inst_module_node)

            if cur_module_identifier_dict[key][k] not in inst_module_design_trees_dict:
                inst_module_design_trees_dict[cur_module_identifier_dict[key][k]] = [len(inst_module_design_trees) - 1]
            else:
                inst_module_design_trees_dict[cur_module_identifier_dict[key][k]].append(
                    len(inst_module_design_trees) - 1
                )

            repeat_decl_dict[cur_module_identifier_dict[key][k]] = visitor.repeat_declr

    bar.next()

    # Step 3.2. Further collect information
    cur_list_of_ports_lhs = []
    cur_list_of_ports_lhs_width = []
    cur_list_of_ports_width = []
    cur_list_of_ports_direction: List[SignalDirection] = []
    cur_list_of_ports_type: List[SignalType] = []
    cur_list_of_data_type: List[str] = []
    cur_dict_of_ports = {}

    index_dict_of_ports = {}

    for key in inst_module_design_trees_dict:
        indexs = inst_module_design_trees_dict[key]
        for i in indexs:
            visitor = InstModulePortVisitor(cur_module_identifier_dict, cur_prefixs, cur_dict_of_parameters)
            visitor.visit(inst_module_design_trees[i])
            index_left = len(cur_list_of_ports_lhs)
            index_right = index_left + len(visitor.list_of_ports_lhs)
            index_dict_of_ports[key] = [index_left, index_right]
            cur_list_of_ports_lhs = cur_list_of_ports_lhs + visitor.list_of_ports_lhs
            cur_list_of_ports_lhs_width = cur_list_of_ports_lhs_width + visitor.list_of_ports_width
            cur_list_of_ports_width = cur_list_of_ports_width + visitor.list_of_ports_width
            cur_list_of_ports_direction.extend(visitor.list_of_ports_direction)
            cur_list_of_ports_type.extend(visitor.list_of_ports_type)
            cur_list_of_data_type.extend(visitor.list_of_data_type)

    for i in range(0, len(cur_list_of_ports_lhs)):
        cur_dict_of_ports[cur_list_of_ports_lhs[i]] = {
            "width": cur_list_of_ports_lhs_width[i],
            "direction": cur_list_of_ports_direction[i],
            "type": cur_list_of_ports_type[i],
        }

    bar.next()

    # Step 3.3 Combine materials to be replaced
    cur_new_variable = []
    cur_new_assign = []
    new_assign_index_dict = {}

    for key in cur_module_identifier_dict:
        instance_names = cur_module_identifier_dict[key]
        for instance_name in instance_names:
            indexs = index_dict_of_ports[instance_name]
            index_left = len(cur_new_assign)
            for i in range(indexs[0], indexs[1]):
                if cur_list_of_data_type[i] != "":
                    cur_new_variable.append(
                        cur_list_of_data_type[i]
                        + cur_list_of_ports_lhs_width[i]
                        + " "
                        + instance_name
                        + "___"
                        + cur_list_of_ports_lhs[i]
                        + ";"
                    )
                elif cur_list_of_ports_type[i] == SignalType.REG:
                    if cur_list_of_ports_lhs[i] not in repeat_decl_dict[instance_name]:
                        cur_new_variable.append(
                            "reg"
                            + cur_list_of_ports_lhs_width[i]
                            + " "
                            + instance_name
                            + "___"
                            + cur_list_of_ports_lhs[i]
                            + ";"
                        )
                else:
                    if cur_list_of_ports_lhs[i] not in repeat_decl_dict[instance_name]:
                        cur_new_variable.append(
                            "wire"
                            + cur_list_of_ports_lhs_width[i]
                            + " "
                            + instance_name
                            + "___"
                            + cur_list_of_ports_lhs[i]
                            + ";"
                        )

                if cur_list_of_ports_direction[i] == SignalDirection.INPUT:
                    rhs = dict_of_lhs_to_rhs[instance_name].get(cur_list_of_ports_lhs[i])
                    if rhs is None:
                        continue

                    if rhs == "" or rhs.strip() == "":
                        continue

                    cur_new_assign.append(
                        "assign " + instance_name + "___" + cur_list_of_ports_lhs[i] + " = " + rhs + ";"
                    )
                else:
                    rhs = dict_of_lhs_to_rhs[instance_name].get(cur_list_of_ports_lhs[i])
                    if rhs is None:
                        continue

                    if rhs == "" or rhs.strip() == "":
                        continue

                    cur_new_assign.append(
                        "assign " + rhs + " = " + instance_name + "___" + cur_list_of_ports_lhs[i] + ";"
                    )

            new_assign_index_dict[instance_name] = [index_left, len(cur_new_assign)]

    bar.next()

    inst_module_designs = []
    for k in range(0, len(cur_prefixs)):
        visitor = InstBodyVisitor()
        visitor.visit(inst_module_nodes[k])
        inst_module_nodes[k] = visitor.inst_module_node
        inst_module_designs.append(visitor.text)

    bar.next()

    # 3.4 Stitch together the obtained materials to get the final data
    insert_parts = {}
    for k in range(0, len(cur_prefixs)):
        visitor = InstBodyVisitor2()
        visitor.visit(inst_module_nodes[k])
        insert_parts[cur_prefixs[k]] = inst_module_designs[k][visitor.start : visitor.stop]

    bar.next()

    visitor = IdentifierVisitor(
        cur_name_of_module_instance=cur_name_of_module_instances,
        design=top_instance_str,
        cur_dict_of_parameters=cur_dict_of_parameters,
        top_module=top_module,
        cur_new_variable=cur_new_variable,
        insert_parts=insert_parts,
        cur_new_assign=cur_new_assign,
        new_var_index=index_dict_of_ports,
        new_assign_index=new_assign_index_dict,
    )
    visitor.visit(top_node_tree)

    bar.next()

    flatten_design = replace_module(design, top_module, "\n".join(visitor.tmp_design))

    bar.next()
    bar.finish()

    return False, flatten_design

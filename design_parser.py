from antlr4_systemverilog import InputStream, CommonTokenStream
from antlr4_systemverilog.systemverilog import SystemVerilogLexer, SystemVerilogParser, SystemVerilogPreParser
from antlr4.ListTokenSource import ListTokenSource
import re


def parse(Design):
    lexer = SystemVerilogLexer(InputStream(Design))
    token_stream = CommonTokenStream(lexer)

    # Fill the Token stream
    token_stream.fill()

    # Create an empty list to store Tokens from the DIRECTIVES channel
    directive_tokens = []

    # Iterate through all Tokens in the token_stream
    for token in token_stream.tokens:
        # Check if the token's channel is DIRECTIVES
        if token.channel != 2:
            # If yes, add the token to the directive_tokens list
            directive_tokens.append(token)

    # If no Tokens from the DIRECTIVES channel are found, return EOF directly
    if not directive_tokens:
        print("No DIRECTIVES tokens found")
        return None

    # Create a new TokenStream containing only Tokens from the DIRECTIVES channel
    directive_token_source = ListTokenSource(directive_tokens)
    filtered_token_stream = CommonTokenStream(directive_token_source)

    # Create a Parser and parse
    parser = SystemVerilogParser(filtered_token_stream)
    return parser


"This function is used to convert the systemverilog to a tree"


def parse_design_to_tree(Design):
    parser = parse(Design)
    tree = parser.source_text()
    return tree


def parse_port_to_tree(Design):
    parser = parse(Design)
    tree = parser.list_of_port_declarations()
    return tree


def parse_parameter_to_tree(Design):
    parser = parse(Design)
    tree = parser.module_parameter_port_list()
    return tree


def parse_module_to_tree(Design):
    parser = parse(Design)
    tree = parser.module_item()
    return tree


def parse_net_declare_to_tree(Design):
    parser = parse(Design)
    tree = parser.net_declaration()
    return tree


def parse_reg_declare_to_tree(Design):
    parser = parse(Design)
    tree = parser.reg_declaration()
    return tree


def parse_mod_ins_to_tree(Design):
    parser = parse(Design)
    tree = parser.module_instantiation()
    return tree


def extract_module(verilog_code: str, module_name: str) -> str:
    """
    Extract the definition of the specified module from Verilog code.

    :param verilog_code: Verilog code string containing the entire design
    :param module_name: Name of the module to extract
    :return: Extracted module string
    """

    # Use regular expressions to match the beginning and end of the module
    # This regular expression matches content between "module module_name" and "endmodule"
    # \b ensures module_name is matched as a whole word, followed by whitespace or parentheses
    module_pattern = re.compile(rf"\bmodule\s+{module_name}\b\s*.*?endmodule", re.S)

    # Search for the module
    match = module_pattern.search(verilog_code)

    if match:
        # Return the matched module string
        return match.group(0)
    else:
        # If the corresponding module is not found, return an empty string or a prompt
        return f"Error: Module '{module_name}' not found."


def extract_modules(verilog_code: str, module_name: dict) -> str:
    """
    Extract the definitions of specified modules from Verilog code.

    :param verilog_code: Verilog code string containing the entire design
    :param module_name: Names of the modules to extract
    :return: Extracted module strings
    """

    # Use regular expressions to match the beginning and end of the modules
    # This regular expression matches content between "module module_name" and "endmodule"
    # \b ensures module_name is matched as a whole word, followed by whitespace or parentheses
    instance_design_str_list = []
    for key in module_name:
        module_pattern = re.compile(rf"\bmodule\s+{key}\b\s*.*?endmodule", re.S)
        match = module_pattern.search(verilog_code)
        if match:
            instance_design_str_list.append(match.group(0))

    if instance_design_str_list != []:
        # Return the matched module strings
        return instance_design_str_list
    else:
        # If the corresponding modules are not found, return an empty string or a prompt
        return f"Error: Module '{module_name}' not found."


def replace_module(verilog_code: str, module_name: str, new_module_code: str) -> str:
    """
    Replace the specified module in Verilog code with a new module definition, and manually handle special characters.

    :param verilog_code: Verilog code string containing the entire chip design
    :param module_name: Name of the module to replace
    :param new_module_code: New module definition string
    :return: Updated Verilog code with the replaced module
    """

    new_module_code = extract_module(new_module_code, module_name)

    # Regular expression to match the target module
    module_pattern = re.compile(rf"module\s+{module_name}\s*.*?endmodule", re.S)

    # Manually escape percentage signs and backslashes in the replacement string
    safe_new_module_code = new_module_code.replace("\\", "\\\\")

    # Use re.sub() for replacement
    updated_verilog_code = re.sub(module_pattern, safe_new_module_code, verilog_code)

    return updated_verilog_code

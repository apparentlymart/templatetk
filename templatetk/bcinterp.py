# -*- coding: utf-8 -*-
"""
    templatetk.bcinterp
    ~~~~~~~~~~~~~~~~~~~

    Provides basic utilities that help interpreting the bytecode that comes
    from the AST transformer.

    :copyright: (c) Copyright 2011 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
import os
import sys
from types import CodeType
from itertools import izip

from .asttransform import to_ast
from .runtime import RuntimeInfo
from .nodes import Node


def compile_ast(ast, filename='<string>'):
    """Compiles an AST node to bytecode"""
    if isinstance(filename, unicode):
        filename = filename.encode('utf-8')

    # XXX: this is here for debugging purposes during development.
    if os.environ.get('TEMPLATETK_AST_DEBUG'):
        from astutil.codegen import to_source
        print >> sys.stderr, '-' * 80
        ast = to_source(ast)
        print >> sys.stderr, ast
        print >> sys.stderr, '-' * 80

    return compile(ast, filename, 'exec')


def encode_filename(filename):
    """Python requires filenames to be strings."""
    if isinstance(filename, unicode):
        return filename.encode('utf-8')
    return filename


def run_bytecode(code_or_node, filename=None):
    """Evaluates given bytecode, an AST node or an actual ATST node.  This
    returns a dictionary with the results of the toplevel bytecode execution.
    """
    if isinstance(code_or_node, Node):
        code_or_node = to_ast(code_or_node)
        if filename is None:
            filename = encode_filename(code_or_node.filename)
    if not isinstance(code_or_node, CodeType):
        if filename is None:
            filename = '<string>'
        code_or_node = compile_ast(code_or_node, filename)
    namespace = {}
    exec code_or_node in namespace
    return namespace


def recursive_make_undefined(config, targets):
    result = []
    for name in targets:
        if isinstance(name, tuple):
            result.append(recursive_make_undefined(config, name))
        else:
            result.append(config.undefined_variable(name))
    return tuple(result)


def _unpack_tuple_silent(config, values, targets):
    for name, value in izip(targets, values):
        if isinstance(name, tuple):
            yield lenient_unpack_helper(config, value, name)
        else:
            yield value
    diff = len(targets) - len(values)
    for x in xrange(diff):
        yield config.undefined_variable(targets[len(targets) + x - 1])


def lenient_unpack_helper(config, iterable, targets):
    """Can unpack tuples to target names without raising exceptions.  This
    is used by the compiled as helper function in case the config demands
    this behavior.
    """
    try:
        values = tuple(iterable)
    except TypeError:
        if not config.allow_noniter_unpacking:
            raise
        return recursive_make_undefined(config, targets)

    if config.strict_tuple_unpacking:
        return values

    return _unpack_tuple_silent(config, values, targets)


def resolve_call_args(*args, **kwargs):
    """A simple helper function that keeps the compiler code clean.  This
    is used at runtime as a callback for forwarding calls.
    """
    return args, kwargs


def register_block_mapping(info, mapping):
    def _make_executor(render_func):
        def executor(info, vars):
            rtstate = RuntimeState(vars, info.config, info.template_name)
            return render_func(rtstate)
        return executor
    for name, render_func in mapping.iteritems():
        info.register_block(name, _make_executor(render_func))


class RuntimeState(object):
    runtime_info_class = RuntimeInfo

    def __init__(self, context, config, template_name, info=None):
        self.context = context
        self.config = config
        if info is None:
            info = self.runtime_info_class(self.config, template_name)
        self.info = info

    def get_template(self, template_name):
        """Looks up a template."""
        return self.info.get_template(template_name)

    def evaluate_block(self, name, vars=None, level=1):
        """Evaluates a single block."""
        return self.info.evaluate_block(name, level, vars)

    def export_var(self, name, value):
        """Called by the runtime for toplevel assignments."""
        self.info.exports[name] = value

    def lookup_var(self, name):
        """The compiled code will try to find unknown variables with the
        help of this function.  This is the bytecode compiled equivalent
        of :meth:`templatetk.interpreter.InterpreterState.resolve_var` but
        only called for variables that are not yet resolved.
        """
        try:
            return self.context[name]
        except KeyError:
            return self.config.undefined_variable(name)


class MultiMappingLookup(object):

    def __init__(self, mappings):
        self.mappings = mappings

    def __contains__(self, key):
        for d in self.mappings:
            if key in d:
                return True
        return False

    def __getitem__(self, key):
        for d in self.mappings:
            try:
                return d[key]
            except KeyError:
                continue
        raise KeyError(key)

    def __iter__(self):
        found = set()
        for d in self.mappings:
            for key in d:
                if key not in found:
                    found.add(key)
                    yield key

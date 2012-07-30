#!/usr/bin/env python
# Copyright (c) 2012 Turbulenz Limited

import os

from glob import glob
from platform import system, machine
from subprocess import Popen, PIPE, STDOUT
from os.path import join as path_join, isdir as path_isdir, splitext as path_splitext, exists as path_exists, \
    split as path_split, expanduser as path_expanduser

from base64 import urlsafe_b64encode
from hashlib import sha1
from shutil import copyfile, rmtree
from optparse import OptionParser
from distutils.version import StrictVersion
from logging import debug, info, warning, error, basicConfig as logging_config

from simplejson import dump as json_dump

from genmapping import gen_mapping

BUILDVERSION = '0.9.1'

ENGINEVERSION = '0.20.2'
SDKVERSION = '0.20.2'

#User defined variables: Only set if different from default

try:
    USER_SDK_PATH = os.environ['TURBULENZ_SDK']
except KeyError:
    pass
#USER_ENV_PATH = USER_SDK_PATH + "\env"
USER_APP_JSLIB_PATH = path_join('scripts', 'turbulenz')

# Clone of sh function from utils.turbulenz

# pylint: disable=W0231
class CalledProcessError(Exception):
    def __init__(self, retcode, cmd, output=None):
        self.retcode = retcode
        self.cmd = cmd
        self.output = output
    def __str__(self):
        return "Command '%s' returned non-zero exit status %d" % (self.cmd, self.retcode)
# pylint: enable=W0231

def exec_command(command, cwd=None, env=None, verbose=True, console=False,
                 ignore=False, shell=True, wait=True):

    if shell and isinstance(command, list):
        command = ' '.join(command)
    elif not shell and isinstance(command, basestring):
        command = command.split()

    if verbose:
        print 'Executing: %s' % command

    if wait:
        if console:
            process = Popen(command, stderr=STDOUT, cwd=cwd, shell=shell)
        else:
            process = Popen(command, stdout=PIPE, stderr=STDOUT, cwd=cwd, shell=shell)

        output, _ = process.communicate()
        output = str(output)
        retcode = process.poll()
        if retcode:
            if ignore is False:
                raise CalledProcessError(retcode, command, output=output)

        if output is not None:
            output = output.rstrip()

        return output
    else:
        if system() == 'Windows':
            detached_process = 0x00000008
            Popen(command, creationflags=detached_process, cwd=cwd, shell=shell)
        else:
            Popen(command, stdout=PIPE, stderr=STDOUT, cwd=cwd, shell=shell)

############################################################

def rm(path):
    if path_exists(path):
        debug('rm: %s' % path)
        os.remove(path)

def rmdir(path):
    if path_isdir(path):
        debug('rmdir: %s' % path)
        rmtree(path)

def mkdir(path):
    if not path_isdir(path):
        debug('mkdir: %s' % path)
        os.makedirs(path)

############################################################

def check_path_py_tools(env, options):

    path = None
    env_name = 'PYTOOLS_ROOT'
    try:
        env_path = env['ENV_PATH']
        turbulenz_os = env['TURBULENZ_OS']
    except KeyError as e:
        error("Missing required env: %s " % str(e))
        return (env_name, None)

    if turbulenz_os == 'macox' or turbulenz_os == 'linux64' or turbulenz_os or 'linux32':
        path = path_join(env_path, 'bin')
    elif turbulenz_os == 'win32':
        path = path_join(env_path, 'Scripts')
    else:
        error("Platform not recognised. Cannot configure build.")
        return (env_name, None)

    if path_exists(path):
        env[env_name] = path
    else:
        warning("Can't find optional %s path (Not set)" % (env_name))
    return (env_name, path)

def check_py_tool(env_name, tool_name, env, options, exp_version_str=None,
                  default_arg=None):

    if env_name is None or env_name == '':
        error("No env_name specified")
        return (None, None)

    info("Checking: " + tool_name)
    tool = None

    def _default():
        try:
            turbulenz_os = env['TURBULENZ_OS']
        except KeyError as e:
            error("Missing required env: %s " % str(e))
            return None

        if turbulenz_os == 'macosx' or turbulenz_os == 'linux64' or turbulenz_os == 'linux32':
            tool = tool_name
        elif turbulenz_os == 'win32':
            tool = tool_name
        else:
            error("Platform not recognised. Cannot configure build.")
            return None

        debug("turbulenz_os: %s" % turbulenz_os)
        info("TOOL: %s" % tool)
        return tool

    def _pytools_root():
        # Attempt to use tools_root
        info("Attempting to look in the python tools root")

        try:
            pytools_root = env['PYTOOLS_ROOT']
        except KeyError:
            error("Missing required env: %s " % str(e))
            return None

        tool = path_join(pytools_root, tool_name + '.py')
        if not path_exists(tool):
            error("Tool doesn't exist: %s" % tool)
            info("Path: %s" % tool)

        return tool

    def _pytools_local():
        tool = path_join('tools', tool_name)
        if not path_exists(tool):
            error("Tool doesn't exist: %s" % tool)
            info("Path: %s" % tool)

        return tool

    for t in [_default, _pytools_root, _pytools_local]:
        tool = t()
        if not tool:
            return (env_name, None)

        # Check tool runs
        info("Calling tool: " + tool)
        args = [tool]
        if default_arg:
            args.append(default_arg)
        try:
            result = exec_command(args, verbose=options.verbose, console=options.verbose)
        except CalledProcessError:
            warning("Failed to run tool as:")
            print args
            warning("You're environment may not be setup correctly")
        else:
            break
    else:
        error("Failed to find tool: %s" % tool_name)
        return (env_name, None)

    # Tool runs, check version
    env[env_name] = tool

    info("Checking version")
    # Check the version info matches
    if exp_version_str:
        args = [tool, '--version']
        try:
            result = exec_command(args, verbose=options.verbose, console=options.verbose)
            if result != exp_version_str:
                error("Tool version returned: %s" % result)
                return False

        except CalledProcessError:
            error("Tool failed to print version")
            return False

    return (env_name, tool)

def check_cgfx_tool(env, options):

    env_name = 'CGFX2JSON'
    try:
        tools_root = env['TOOLS_ROOT']
        turbulenz_os =  env['TURBULENZ_OS']
        exe = env['EXE_EXT_OS']
    except KeyError as e:
        error("Missing required env: %s " % str(e))
        return (env_name, None)

    tool = path_join(tools_root, 'bin', turbulenz_os, 'cgfx2json') + exe
    if not path_exists(tool):
        error("Can't find the cgfx2json tool: %s" % tool)
        return (env_name, None)

    args = [tool]
    try:
        result = exec_command(args, verbose=options.verbose, console=options.verbose)
    except CalledProcessError:
        error("Failed to run tool cgfx2json:")
        print args
        return (env_name, None)
    if options.verbose:
        print "Result: %s" % str(result)

    env[env_name] = tool
    return (env_name, tool)

def configure(env, options):

    app_root = os.getcwd()
    exe = ''
    turbulenz_os = ''

    system_name = system()
    machine_name = machine()
    if system_name == 'Linux':
        if machine_name == 'x86_64':
            turbulenz_os = 'linux64'
        else:
            turbulenz_os = 'linux32'
    elif system_name == 'Windows':
        turbulenz_os = 'win32'
        exe = '.exe'
    elif system_name == 'Darwin':
        turbulenz_os = 'macosx'

    if turbulenz_os == '':
        error("Build not supported on this system: %s platform: %s" % (system_name, machine_name))
        return False

    env['TURBULENZ_OS'] = turbulenz_os
    env['EXE_EXT_OS'] = exe

    try:
        engine_version_minor = StrictVersion('.'.join(ENGINEVERSION.split('.')[0:2]))
        engine_version = StrictVersion(ENGINEVERSION)
        env['ENGINE_VERSION_STR'] = ENGINEVERSION
        env['ENGINE_VERSION'] = engine_version
    except ValueError:
        error("Version of Engine not recognised: %s" % ENGINEVERSION)
        return False

    try:
        sdk_version_minor = StrictVersion('.'.join(SDKVERSION.split('.')[0:2]))
        sdk_version = StrictVersion(SDKVERSION)
        env['SDK_VERSION_STR'] = SDKVERSION
        env['SDK_VERSION'] = sdk_version
    except ValueError:
        error("Version of SDK not recognised: %s" % SDKVERSION)
        return False

    if engine_version != sdk_version:
        if options.verbose:
            warning("Target engine and SDK version don't match. Engine: %s, SDK: %s" % (engine_version, sdk_version))

    if engine_version_minor != sdk_version_minor:
        error("Target engine and SDK minor versions are not compatible. Engine: %s, SDK: %s" % (engine_version_minor, sdk_version_minor))
        return False

    if 'USER_SDK_PATH' in globals():
        sdk_root = path_expanduser(USER_SDK_PATH)
    else:
        if turbulenz_os == 'win32':
            sdk_root = path_expanduser(path_join('C:\\', 'Turbulenz', 'SDK', SDKVERSION))
        elif turbulenz_os == 'macosx' or turbulenz_os == 'linux32' or turbulenz_os == 'linux64':
            sdk_root = path_expanduser(path_join('~/', 'Turbulenz', 'SDK', SDKVERSION))
        else:
            error("Platform not recognised. Cannot configure build.")
            return False

    if not path_exists(sdk_root):
        print "Can't find the SDK specified: %s" % sdk_root
        print """If you are using a non-standard SDK path, either:
  1. define the TURBULENZ_SDK environment variable, or
  2. set it in this file using USER_SDK_PATH"""
        return False

    # Check expected env
    env_path = os.environ['VIRTUAL_ENV']

    if 'USER_ENV_PATH' in globals():
        env_path_expt = USER_ENV_PATH
    else:
        env_path_expt = path_join(sdk_root, 'env')

    if env_path.lower() != env_path_expt.lower():
        error("The environment you are running from is not the same as expected for the target SDK")
        print "Expected: %s, Actual: %s" % (env_path_expt, env_path)
        print "You may need to activate a different SDK environment."
        print "If you are using a different environment set it in this file using USER_ENV_PATH"
        return False

    env['ENV_PATH'] = env_path

    env['APP_ROOT'] = app_root
    env['APP_PAIR'] = (app_root + ',./')
    env['SDK_ROOT'] = sdk_root

    tools_root = path_join(sdk_root, 'tools')
    env['TOOLS_ROOT'] = tools_root
    env['PYTOOLS_ROOT'] = path_join(app_root, 'tools')

    (_, pytools_root) = check_path_py_tools(env, options)
    if pytools_root is None:
        warning("Path pytools_root has not been set (optional)")

    # Check for the existence of tools
    if sdk_version < StrictVersion('0.19.0'):
        required = dict(JS2TZJS=True,
                        HTML2TZHTML=True,
                        CGFX2JSON=False)
    else:
        required = dict(MAKETZJS=True,
                        MAKEHTML=True,
                        CGFX2JSON=False)

    (DAE2JSON, dae2json) = check_py_tool('DAE2JSON', 'dae2json', env, options)
    if dae2json is None:
        raise Exception("can't find dae2json tool")
    info("dae2json: %s" % env['DAE2JSON'])

    (BMFONT2JSON, bmfont2json) = check_py_tool('BMFONT2JSON', 'bmfont2json', env, options)
    if bmfont2json is None:
        raise Exception("can't find bmfont2json tool")
    info("bmfont2json: %s" % env['BMFONT2JSON'])

    (MC2JSON, mc2json) = check_py_tool('MC2JSON', 'mc2json', env, options, default_arg='--version')
    if mc2json is None:
        warning("Couldn't find mc2json tool (optional)")
    else:
        info("mc2json: %s" % env['MC2JSON'])

    for (env_name, req) in required.iteritems():
        if env_name == 'JS2TZJS':
            (JS2TZJS, js2tzjs) = check_py_tool('JS2TZJS', 'js2tzjs', env, options)
            if js2tzjs is None:
                if req:
                    error("Couldn't find js2tzjs tool (required)")
                    return False
                else:
                    warning("Couldn't find js2tzjs tool (optional)")
        if env_name == 'HTML2TZHTML':
            (HTML2TZHTML, html2tzhtml) = check_py_tool('HTML2TZHTML','html2tzhtml', env, options)
            if html2tzhtml is None:
                if req:
                    error("Couldn't find html2tzhtml tool (required)")
                    return False
                else:
                    warning("Couldn't find html2tzhtml tool (optional)")
        if env_name == 'MAKETZJS':
            (MAKETZJS, maketzjs) = check_py_tool('MAKETZJS', 'maketzjs', env, options, default_arg='--version')
            if maketzjs is None:
                if req:
                    error("Couldn't find maketzjs tool (required)")
                    return False
                else:
                    warning("Couldn't find maketzjs tool (optional)")
        if env_name == 'MAKEHTML':
            (MAKEHTML, makehtml) = check_py_tool('MAKEHTML', 'makehtml', env, options, default_arg='--version')
            if makehtml is None:
                if req:
                    error("Couldn't find makehtml tool (required)")
                    return False
                else:
                    warning("Couldn't find makehtml tool (optional)")

        if env_name == 'CGFX2JSON':
            (CGFX2JSON, cgfx2json) = check_cgfx_tool(env, options)
            if cgfx2json is None:
                if req:
                    error("Couldn't find cgfx2json tool (required)")
                    return False
                else:
                    warning("Couldn't find cgfx2json tool (optional)")

    env['MAPPING_TABLE'] = 'mapping_table.json'
    env['APP_MAPPING_TABLE'] = path_join(app_root, env['MAPPING_TABLE'])
    env['APP_STATICMAX'] = path_join(app_root, 'staticmax')
    env['APP_TEMPLATES'] = path_join(app_root, 'templates')
    env['APP_SHADERS'] = path_join(app_root, 'assets', 'shaders')
    env['APP_MATERIALS'] = path_join(app_root, 'assets', 'materials')
    env['APP_MODELS'] = path_join(app_root, 'assets', 'models')
    env['APP_TEXTURES'] = path_join(app_root, 'assets', 'textures')
    env['APP_SOUNDS'] = path_join(app_root, 'assets', 'sounds')
    env['APP_FONTS'] = path_join(app_root, 'assets', 'fonts')
    env['APP_SCRIPTS'] = path_join(app_root, 'scripts')

    if 'USER_APP_JSLIB_PATH' in globals():
        env['APP_JSLIB'] = path_join(app_root, USER_APP_JSLIB_PATH)
    else:
        env['APP_JSLIB'] = path_join(app_root)

    return True

def run_makehtml(env, options, input=None, mode=None, output=None, templates=[], code=None, template=None):
    try:
        makehtml = env['MAKEHTML']
    except KeyError as e:
        error("Missing required env: %s " % str(e))
        raise CalledProcessError(1, 'makehtml')

    args = [makehtml]
    if mode is not None:
        args.append('--mode')
        args.append(mode)
    if output is not None:
        args.append('-o')
        args.append(output)
    for t in templates:
        args.append('-t')
        args.append(t)
    if code is not None:
        if mode is not None:
            if mode == 'plugin' or mode == 'canvas':
                args.append('--code')
                args.append(code)
            else:
                error("Code was specified, with an unexpected mode: %s" % mode)
                raise CalledProcessError(1, 'makehtml')
        else:
            error("Code was specified without a mode")
            raise CalledProcessError(1, 'makehtml')
    if input is not None:
        args.append(input)
    if template is not None:
        args.append(template)
    return exec_command(args, verbose=options.verbose, console=True, shell=True)

def run_maketzjs(env, options, input=None, mode=None, MF=None, output=None, templates=[]):
    try:
        maketzjs = env['MAKETZJS']
    except KeyError as e:
        error("Missing required env: %s " % str(e))
        raise CalledProcessError(1, 'maketzjs')

    #TODO: version check
    args = [maketzjs]
    if mode is not None:
        args.append('--mode')
        args.append(mode)
    if MF is not None:
        args.append('-M')
        args.append('--MF')
        args.append(MF)
    if output is not None:
        args.append('-o')
        args.append(output)
    for t in templates:
        args.append('-t')
        args.append(t)
    if input is not None:
        args.append(input)

    return exec_command(args, verbose=options.verbose, console=True)

def run_js2tzjs(task):
    src = task['inputs'][0]
    tgt = task['outputs'][0]
    env = task['env']
    args = [env['JS2TZJS'],
            '-i', src,
            '-o', tgt,
            '-t', env['APP_TEMPLATES'],
            '-I', env['SDK_ROOT'],
            '-I', env['APP_ROOT'],
            '-z',
            '--ev', env['ENGINE_VERSION_STR']]

    return exec_command(args, verbose=task['options'].verbose, console=True)

def run_js2tzjs_jsinc(task):
    src = task['inputs'][0]
    tgt = task['outputs'][0]
    env = task['env']
    args = [env['JS2TZJS'],
            '-i', src,
            '-o', tgt,
            '-t', env['APP_TEMPLATES'],
            '-I', env['SDK_ROOT'],
            '-I', env['APP_ROOT'],
            '--ev', env['ENGINE_VERSION_STR']]

    return exec_command(args, verbose=task['options'].verbose, console=True)

def run_cgfx2json(env, options, input=None, output=None):
    try:
        cgfx2json = env['CGFX2JSON']
    except KeyError as e:
        error("Missing required env: %s " % str(e))
        raise CalledProcessError(1, 'cgfx2json')

    #TODO: version check
    args = [cgfx2json]
    if input is not None:
        args.append('-i')
        args.append(input)
    if output is not None:
        args.append('-o')
        args.append(output)
    return exec_command(args, verbose=options.verbose, console=True)

def clean(env):
    try:
        rmdir(env['APP_STATICMAX'])
        rm(env['APP_MAPPING_TABLE'])

        # Aggressive root level cleaning
        for f in os.listdir(env['APP_ROOT']):
            (filename, ext) = path_splitext(f)

            # Also cleans previous SDK content e.g. .jsinc
            if ext in ['.jsinc', '.tzjs', '.html']:
                rm(f)
            if ext == '.js':
                #Only remove canvas js files, might have js in root folder
                (appname, target) = path_splitext(filename)
                if target == '.canvas':
                    rm(f)
                else:
                    warning('[Warning] target %s unknown, ignoring. Not cleaned: %s' % (target, f))
    except OSError as e:
        error('Failed to remove: %s' % str(e))
        return False

    return True

############################################################

def _log_stage(stage):
    print '\n{0}\n{1: ^58}\n{0}\n'.format('-' * 58, stage)

def do_build_code(filepath, env, options):

    builderror = 0
    templates=[env['APP_ROOT'], env['APP_TEMPLATES'], env['APP_JSLIB']]

    (filename, ext) = path_splitext(filepath)

    if ext == '.html':
        (appname, buildtype) = path_splitext(filename)

        if buildtype is not None:
            try:
                (appname, target) = path_splitext(appname)

                html_templates = [ t + "/" + appname + ".html" for t in templates ]
                html_templates = [ path_split(t)[1] \
                                       for t in html_templates if path_exists(t) ]
                # print "HTML templates: %s" % html_templates
                # print "buildtype: %s" % buildtype

                if buildtype == '.development':
                    if options.verbose:
                        warning("'development' should now be 'debug' and has not been built. Change the name of the destination file")
                else:
                    if target == '.canvas':
                        if buildtype == '.debug':
                            run_makehtml(env, options,
                                    input=(appname + '.js'),
                                    mode='canvas-debug',
                                    output=filepath,
                                    templates=templates,
                                    template=" ".join(html_templates))

                        elif buildtype == '.release':
                            run_makehtml(env, options,
                                    input=(appname + '.js'),
                                    mode='canvas',
                                    output=filepath,
                                    templates=templates,
                                    code=(appname + target + '.js'),
                                    template=" ".join(html_templates))
                        else:
                            if options.verbose:
                                warning("Build type not recognised: %s" % buildtype)
                    elif target == '.default':
                        (appname, defaultTarget) = path_splitext(appname)
                        if defaultTarget == '.canvas':
                            if buildtype == '.debug':
                                run_makehtml(env, options,
                                        input=(appname + '.js'),
                                        mode='canvas-debug',
                                        output=filepath,
                                        templates=templates)
                            elif buildtype == '.release':
                                run_makehtml(env, options,
                                        input=(appname + '.js'),
                                        mode='canvas',
                                        code=(appname + defaultTarget + '.js'),
                                        output=filepath,
                                        templates=templates)
                            else:
                                if options.verbose:
                                    warning("Build type not recognised: %s" % buildtype)
                        if defaultTarget == '':
                            if buildtype == '.debug':
                                run_makehtml(env, options,
                                        input=(appname + '.js'),
                                        mode='plugin-debug',
                                        output=filepath,
                                        templates=" ".join(html_templates))
                            elif buildtype == '.release':
                                run_makehtml(env, options,
                                        input=(appname + '.js'),
                                        mode='plugin',
                                        code=(appname + '.tzjs'),
                                        output=filepath,
                                        templates=" ".join(html_templates))
                            else:
                                if options.verbose:
                                    warning("Build type not recognised: %s" % buildtype)
                        if buildtype == '.debug':
                            run_makehtml(env, options,
                                    input=(appname + '.js'),
                                    mode='plugin-debug',
                                    output=filepath,
                                    templates=" ".join(html_templates))
                        elif buildtype == '.release':
                            run_makehtml(env, options,
                                    input=(appname + '.js'),
                                    mode='plugin',
                                    output=filepath,
                                    templates=" ".join(html_templates))
                        else:
                            if options.verbose:
                                warning("Build type not recognised: %s" % buildtype)
                    elif target == '':
                        # Blank target is plugin
                        if buildtype == '.debug':
                            run_makehtml(env, options,
                                    input=(appname + '.js'),
                                    mode='plugin-debug',
                                    output=filepath,
                                    templates=templates,
                                    template=" ".join(html_templates))
                        elif buildtype == '.release':
                            run_makehtml(env, options,
                                    input=(appname + '.js'),
                                    mode='plugin',
                                    code=(appname + target + '.tzjs'),
                                    output=filepath,
                                    templates=templates,
                                    template=" ".join(html_templates))
                        else:
                            warning("Build type not recognised: %s" % buildtype)
                    else:
                        warning("Target not recognised: %s" % target)
            except CalledProcessError as e:
                builderror = 1
                error('Command failed: %s' % str(e))

    elif ext == '.tzjs':
        try:
            if env['SDK_VERSION'] < StrictVersion('0.19.0'):
                run_js2tzjs({
                    'inputs': [filename + '.js'],
                    'outputs': [filepath],
                    'env': env,
                    'options': options
                })
            else:
                (appname, target) = path_splitext(filename)
                if target == '':
                    run_maketzjs(env, options,
                            mode='plugin',
                            input=(appname + '.js'),
                            output=filepath,
                            templates=templates)
                else:
                    if options.verbose:
                        warning("Target not recognised: %s" % target)
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

    elif ext == '.js':
        try:
            if env['SDK_VERSION'] >= StrictVersion('0.19.0'):
                (appname, target) = path_splitext(filename)
                if target == '.canvas':

                    #dependency_file = appname + '.deps.js'

                    run_maketzjs(env, options,
                            input=(appname + '.js'),
                            mode='canvas',
                            #MF= dependency_file,
                            output=filepath,
                            templates=templates)

                    if options.closure:
                        google_compile(dependency_file, filename + ext)

                else:
                    if options.verbose:
                        warning("Target not recognised: %s" % target)
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

    elif ext == '.jsinc':
        try:
            run_js2tzjs_jsinc({
                'inputs': [filename + '.js'],
                'outputs': [filepath],
                'env': env,
                'options': options
            })
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

def google_compile(dependency_file, output_file):

    f = open(dependency_file, 'r')

    file_contents = f.read()
    dependency_sets = file_contents.split('\n\n')

    dependencies = ''

    for dependency_set in dependency_sets:
        dep_set_split = dependency_set.split(' :')

        if (len(dep_set_split) > 1):
            deps = dep_set_split[1]

            file_list = deps.split()

            for file in file_list:
                file.strip()

                if (file != ':' and file != '\\'):
                    print file
                    dependencies += ' --js ' + file

    # Create flag file
    flag_file_path = 'flagfile.txt'
    flag_file = open(flag_file_path, 'w')

    flag_file.write(dependencies)
    flag_file.close()

    optimization_level = 'SIMPLE_OPTIMIZATIONS'
    #optimization_level = 'ADVANCED_OPTIMIZATIONS'

    args = [
            'java',
            '-jar',
            'build/compiler.jar',
            '--version',
            '--compilation_level',
            optimization_level,
            '--flagfile',
            flag_file_path,
            '--js_output_file',
            output_file,
            '--warning_level',
            'DEFAULT'
        ]

    _log_stage('RUNNING CLOSURE COMPILER')
    exec_command(args, console=True, verbose=True, shell=True)

def do_build(src, dest, env, options):

    builderror = 0
    templates=[env['APP_ROOT'], env['APP_TEMPLATES'], env['APP_JSLIB']]

    (filename, ext) = path_splitext(src)

    if ext == '.cgfx':
        try:
            run_cgfx2json(env, options, input=src, output=dest)
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

    elif ext == '.dae':
        try:
            exec_command("%s -i %s -o %s" % (env['DAE2JSON'], src, dest))
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

    elif ext == '.fnt':
        try:
            exec_command("%s -i %s -o %s" % (env['BMFONT2JSON'], src, dest))
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

    elif ext == '.schematic':
        try:
            exec_command("%s -i %s -o %s" % (env['MC2JSON'], src, dest))
        except CalledProcessError as e:
            builderror = 1
            error('Command failed: ' + str(e))

    else:
        copyfile(src, dest)

    return builderror

def find_non_ascii(path, env):
    non_ascii_count = 0
    for root, dirs, files in os.walk(path):
        for dir in dirs:
            non_ascii_count += find_non_ascii(path_join(root, dir), env)

        for file in [f for f in files if f.endswith('.js')]:
            filepath = path_join(root, file)
            info('Checking: %s' % filepath)

            data = open(filepath)
            line = 0
            for l in data:
                line += 1
                char = 0
                try:
                    for s in list(unicode(l,'utf-8')):
                        char += 1
                        try:
                            s.encode('ascii')
                        except:
                            warning('%s: Non ASCII character at line:%s char:%s' % (filepath, line, char))
                            non_ascii_count += 1
                except UnicodeDecodeError as e:
                    warning('%s: Non ASCII character at line:%s char:%s' % (filepath, line, char))
                    non_ascii_count += 1
            data.close()

    return non_ascii_count

def main():
    parser = OptionParser()
    parser.add_option('--clean', action='store_true', default=False, help="Clean build output")
    parser.add_option('--assets', action='store_true', default=False, help="Build assets")
    parser.add_option('--code', action='store_true', default=False, help="Build code")
    parser.add_option('--all', action='store_true', default=False, help="Build everything")

    parser.add_option('--find-non-ascii', action='store_true', default=False,
                      help="Searches for non ascii characters in the scripts")
    parser.add_option('--template', dest='templateName', help="Specify the template to build")
    parser.add_option('--closure', action='store_true', default=False, help="Use Google Closure to post process")
    parser.add_option('--verbose', action='store_true', help="Prints additional information about the build process")
    (options, args) = parser.parse_args()

    if options.verbose:
        logging_config(level='INFO', format='[%(levelname)s %(module)s@%(lineno)d] %(message)s')
    else:
        logging_config(format='[%(levelname)s] %(message)s')

    env = {}

    _log_stage('CONFIGURING')
    if not configure(env, options):
        error('Failed to configure build')
        return 1

    if options.find_non_ascii:
        _log_stage('NON-ASCII CHARACTERS')
        count = find_non_ascii(env['APP_SCRIPTS'], env)
        if count > 0:
            error("Found non-ascii character in script")
        else:
            info("Only ASCII found!")
        return count

    if options.clean:
        _log_stage('CLEANING')
        success = clean(env)
        if not success:
            error('Failed to clean build')
            return 1
        else:
            info('Cleaned')

    if options.assets or options.all:
        _log_stage("ASSET BUILD (may be slow - only build code with --code)")

        # Mapping table
        mkdir('staticmax')
        (mapping_table_obj, build_deps) = gen_mapping('assets', 'staticmax')
        debug('assets:src:%s' % build_deps)

        # Write mapping table
        print env['MAPPING_TABLE']
        with open(env['APP_MAPPING_TABLE'], 'w') as f:
            json_dump(mapping_table_obj, f, separators=(',', ':'))

        longest = len(max(build_deps, key=len)) + 2
        def _log(src, dst):
            print '{0:-<{longest}}> {1}'.format(src + ' ', dest, longest=longest)

        # Build all asset files
        for src, dest in build_deps.iteritems():
            _log(src, dest)
            result = do_build(src, dest, env, options)
            if result:
                error('Build failed')
                return 1

    if options.code or options.all:
        _log_stage('CODE BUILD')
        if options.templateName:
            code_files = ['%s.js' % path_join('templates', options.templateName)]
        else:
            code_files = glob('templates/*.js')
        debug("code:src:%s" % code_files)

        for src in code_files:
            (code_base, code_ext) = path_splitext(path_split(src)[1])
            code_dests = [ code_base + ".canvas.debug.html",
                           code_base + ".canvas.release.html",
                           code_base + ".canvas.js",
                           code_base + ".debug.html",
                           code_base + ".release.html",
                           code_base + ".tzjs" ]
            debug("code:dest:%s" % code_dests)

            for dest in code_dests:
                print '%s -> %s' % (src, dest)
                do_build_code(dest, env, options)

    _log_stage('END')

    return 0

if __name__ == "__main__":
    exit(main())

#!/usr/bin/env python
# Copyright (c) 2012 Turbulenz Limited

import os

from glob import glob
from platform import system, machine
from subprocess import Popen, PIPE, STDOUT
from os.path import join as path_join, isdir as path_isdir, splitext as path_splitext, exists as path_exists, \
    split as path_split, expanduser as path_expanduser, basename as path_basename, abspath as path_abspath

from base64 import urlsafe_b64encode
from hashlib import sha1
from shutil import copyfile, rmtree
from optparse import OptionParser
from distutils.version import StrictVersion
from logging import debug, info, warning, error, basicConfig as logging_config
from threading import Thread

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

def exec_command(command, cwd=None, env=None, verbose=False, console=False, ignore=False, shell=True, wait=True):
    if shell and isinstance(command, list):
        command = ' '.join(command)
    elif not shell and isinstance(command, basestring):
        command = command.split()

    if verbose:
        print command

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

def check_path_py_tools(env):
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

def check_py_tool(env_name, tool_name, env, options, default_arg=None, required=False):
    if required:
        _warning = warning
        _error = error
    else:
        _warning = info
        _error = info

    info("Searching for tool: %s" % tool_name)

    tools = [
        tool_name,
        path_join(env['PYTOOLS_ROOT'], tool_name),
        path_join(env['PYTOOLS_ROOT'], tool_name + '.py'),
        path_join('tools', tool_name),
        path_join('tools', tool_name + '.py')
    ]

    for tool in tools:
        info("Calling tool: %s" % tool)

        args = [tool]
        if default_arg:
            args.append(default_arg)
        try:
            result = exec_command(args)
        except CalledProcessError:
            _warning("Failed to run tool as: %s" % args)
        else:
            break
    else:
        _error("Failed to find tool: %s" % tool_name)
        return None

    return tool

############################################################

class Tool(object):

    class ConfigurationException(Exception):
        def __init__(self, name, required=False):
            self.name = name
            self.required = required

    name = None
    app = None
    default_arg = None
    ext = None
    configure = None

    tool = None

    required = False
    before = None
    after = None

    def _required(self, sdk_version):
        if self.required:
            if self.before:
                return sdk_version < self.before
            elif self.after:
                return sdk_version >= self.after
            else:
                return True
        else:
            return False

    def __init__(self, env, options, sdk_version):
        required = self._required(sdk_version)
        if self.configure:
            self.tool = self.configure(env, options)
        else:
            self.tool = check_py_tool(self.name, self.app, env, options,
                                      default_arg=self.default_arg,
                                      required=required)

        if not self.tool:
            raise(Tool.ConfigurationException(self.name, required))
        else:
            info("%s: %s" % (self.name, self.tool))

    def build(self, env, options, input, output):
        args = [self.tool, '-i', input, '-o', output]
        exec_command(args, console=True)

class DAE2JSON(Tool):
    name = 'DAE2JSON'
    app = 'dae2json'
    ext = '.dae'

class MATERIAL2JSON(Tool):
    name = 'MATERIAL2JSON'
    app = 'material2json'
    ext = '.material'

class EFFECT2JSON(Tool):
    name = 'EFFECT2JSON'
    app = 'effect2json'
    ext = '.effect'

class LIGHT2JSON(Tool):
    name = 'LIGHT2JSON'
    app = 'light2json'
    ext = '.light'

class XML2JSON(Tool):
    name = 'XML2JSON'
    app = 'xml2json'
    default_arg = '--version'
    ext = '.xml'

class OBJ2JSON(Tool):
    name = 'OBJ2JSON'
    app = 'obj2json'
    default_arg = '--version'
    ext = '.obj'

class BMFONT2JSON(Tool):
    name = 'BMFONT2JSON'
    app = 'bmfont2json'
    ext = '.fnt'

class MC2JSON(Tool):
    name = 'MC2JSON'
    app = 'mc2json'
    default_arg = '--version'
    ext = '.schematic'

    def build(self, env, options, input, output):
        args = [self.tool, '--lower', '--quantise', '--tidy', input, output]
        exec_command(args, console=options.verbose)

class JS2TZJS(Tool):
    name = 'JS2TZJS'
    app = 'js2tzjs'
    required = True
    before = StrictVersion('0.19.0')

class HTML2TZHTML(Tool):
    name = 'HTML2TZHTML'
    app = 'html2tzhtml'
    required = True
    before = StrictVersion('0.19.0')

class MAKETZJS(Tool):
    name = 'MAKETZJS'
    app = 'maketzjs'
    default_arg = '--version'
    required = True
    after = StrictVersion('0.19.0')

    def build(self, env, options, input=None, mode=None, MF=None, output=None, templates=None, closure=None, yui=None):
        templates = templates or [ ]
        args = [self.tool]
        if mode:
            args.extend(['--mode', mode])
        if MF:
            args.extend(['-M', '--MF', MF])
        if output:
            args.extend(['-o', output])
        if closure:
            args.extend(['--closure', closure])
        if yui:
            args.extend(['--yui', yui])
        for t in templates:
            args.extend(['-t', t])
        if input:
            args.append(input)
        exec_command(args, console=True)

class MAKEHTML(Tool):
    name = 'MAKEHTML'
    app = 'makehtml'
    default_arg = '--version'
    required = True
    after = StrictVersion('0.19.0')

    def build(self, env, options, input=None, mode=None, output=None, templates=None, code=None, template=None):
        templates = templates or [ ]
        args = [self.tool]
        if mode:
            args.extend(['--mode', mode])
        if output:
            args.extend(['--output', output])
        for t in templates:
            args.extend(['-t', t])
        if code:
            if mode:
                if mode == 'plugin' or mode == 'canvas':
                    args.extend(['--code', code])
                else:
                    error("Code was specified, with an unexpected mode: %s" % mode)
                    raise CalledProcessError(1, 'makehtml')
            else:
                error("Code was specified without a mode")
                raise CalledProcessError(1, 'makehtml')
        if input:
            args.append(input)
        if template:
            args.append(template)
        exec_command(args, console=True, shell=True)

class JSON2JSON(Tool):
    name = 'JSON2JSON'
    app = 'json2json'
    ext = '.json'

class CGFX2JSON(Tool):
    name = 'CGFX2JSON'
    app = 'cgfx2json'
    ext = '.cgfx'

    def configure(self, env, options):
        tools_root = env['TOOLS_ROOT']
        turbulenz_os =  env['TURBULENZ_OS']
        exe = env['EXE_EXT_OS']

        tool = path_join(tools_root, 'bin', turbulenz_os, 'cgfx2json' + exe)
        if not path_exists(tool):
            error("Can't find the cgfx2json tool: %s" % tool)
            return None

        args = [tool]
        try:
            result = exec_command(args)
        except CalledProcessError:
            info("Failed to run tool cgfx2json: %s" % args)
            return None
        else:
            return tool

############################################################

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
    env['SDK_ROOT'] = sdk_root
    env['TOOLS_ROOT'] = path_join(sdk_root, 'tools')
    env['PYTOOLS_ROOT'] = path_join(app_root, 'tools')

    (_, pytools_root) = check_path_py_tools(env)
    if pytools_root is None:
        warning("Path pytools_root has not been set (optional)")

    tools = { }
    for tool in [DAE2JSON, MATERIAL2JSON, EFFECT2JSON, LIGHT2JSON, XML2JSON, OBJ2JSON, BMFONT2JSON, MC2JSON,
                 JS2TZJS, HTML2TZHTML, MAKETZJS, MAKEHTML,
                 JSON2JSON, CGFX2JSON]:
        try:
            t = tool(env, options, sdk_version)
        except Tool.ConfigurationException as e:
            if e.required:
                error("Couldn't find tool: %s" % e.name)
                return False
            else:
                warning("Couldn't find tool: %s (optional)" % e.name)
        else:
            env[t.name] = t
            tools[t.ext] = t
    env['TOOLS'] = tools
    env['COPY_EXTENSIONS'] = set(['.ogg', '.png', '.jpeg', '.jpg', '.tga', '.dds'])

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

############################################################
############################################################

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

    return exec_command(args, console=True)

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

    return exec_command(args, console=True)

############################################################
############################################################

def _log_stage(stage):
    print '\n{0}\n{1: ^58}\n{0}\n'.format('-' * 58, stage)

def build_code(src, dst, env, options):
    input = path_basename(src)
    appname, _ = path_splitext(input)
    code = '%s.canvas.js' % appname
    tzjs = '%s.tzjs' % appname

    dependency_file = '%s.deps' % src

    templates_dirs = [env['APP_ROOT'], env['APP_TEMPLATES'], env['APP_JSLIB']]
    for t in templates_dirs:
        template = path_join(t, '%s.html' % appname)
        if path_exists(template):
            template = path_basename(template)
            break
    else:
        template = None

    if dst.endswith('.canvas.debug.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='canvas-debug',
                              templates=templates_dirs,
                              template=template)
    elif dst.endswith('.canvas.release.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='canvas',
                              code=code,
                              templates=templates_dirs,
                              template=template)
    elif dst.endswith('.canvas.default.debug.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='canvas-debug',
                              templates=templates_dirs)
    elif dst.endswith('.canvas.default.release.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='canvas',
                              code=code,
                              templates=templates_dirs)
    elif dst.endswith('.canvas.js'):
        if options.closure:
            env['MAKETZJS'].build(env, options, input=input, output=dst,
                                  mode='canvas',
                                  MF=dependency_file,
                                  templates=templates_dirs)
            google_compile(dependency_file, dst, options.closure)
        else:
            env['MAKETZJS'].build(env, options, input=input, output=dst,
                                  mode='canvas',
                                  templates=templates_dirs)
    elif dst.endswith('.debug.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='plugin-debug',
                              templates=templates_dirs,
                              template=template)
    elif dst.endswith('.release.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='plugin',
                              code=tzjs,
                              templates=templates_dirs,
                              template=template)
    elif dst.endswith('.default.debug.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='plugin-debug',
                              templates=templates_dirs)
    elif dst.endswith('.default.release.html'):
        env['MAKEHTML'].build(env, options, input=input, output=dst,
                              mode='plugin',
                              code=tzjs,
                              templates=templates_dirs)
    elif dst.endswith('.tzjs'):
        if env['SDK_VERSION'] < StrictVersion('0.19.0'):
            run_js2tzjs({
                'inputs': [src],
                'outputs': [dst],
                'env': env,
                'options': options
            })
        else:
            env['MAKETZJS'].build(env, options, input=input, output=dst,
                                  mode='plugin',
                                  yui=options.yui,
                                  templates=templates_dirs)
    elif dst.endswith('.jsinc'):
        run_js2tzjs_jsinc({
            'inputs': [src],
            'outputs': [dst],
            'env': env,
            'options': options
        })
    else:
        return False

    return True

def google_compile(dependency_file, output_file, path_to_closure):
    with open(dependency_file, 'r') as f:
        file_contents = f.read()

    dependencies = set([ ])
    for dependency_set in file_contents.split('\n\n'):
        dep_set_split = dependency_set.split(' :')

        if len(dep_set_split) > 1:
            deps = dep_set_split[1]

            file_list = deps.split()

            for f in file_list:
                f.strip()
                if f != ':' and f != '\\':
                    f = path_abspath(f)
                    dependencies.add(f)

    # Create flag file
    flag_file_path = 'flagfile.txt'
    with open(flag_file_path, 'w') as flag_file:
        flag_file.write(' --js '.join(dependencies))

    optimization_level = 'SIMPLE_OPTIMIZATIONS'
    #optimization_level = 'ADVANCED_OPTIMIZATIONS'

    args = [
        'java',
        '-jar',
        path_to_closure,
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
    exec_command(args, console=True, shell=True)

############################################################

def build_asset(src, dest, env, options):
    (_, ext) = path_splitext(src)
    try:
        tool = env['TOOLS'].get(ext, None)
        if tool:
            tool.build(env, options, src, dest)
        elif ext in env['COPY_EXTENSIONS']:
            copyfile(src, dest)
        else:
            warning('No tool for: %s (skipping)' % src)
            return False
    except CalledProcessError as e:
        error('Command failed: %s' % e)
        return False
    else:
        return True

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

############################################################

def main():
    parser = OptionParser()
    parser.add_option('--clean', action='store_true', default=False, help="Clean build output")
    parser.add_option('--assets', action='store_true', default=False, help="Build assets")
    parser.add_option('--code', action='store_true', default=False, help="Build code")
    parser.add_option('--all', action='store_true', default=False, help="Build everything")

    parser.add_option('--find-non-ascii', action='store_true', default=False,
                      help="Searches for non ascii characters in the scripts")
    parser.add_option('--template', dest='templateName', help="Specify the template to build")
    parser.add_option('--closure', default=None, help="Path to Closure")
    parser.add_option('--yui', default=None, help="Path to YUI")
    parser.add_option('--threads', default=4, help="Number of threads to use")
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
        (mapping_table_obj, build_deps) = gen_mapping('assets', 'staticmax',
            ['.pdf', '.mtl', '.otf', '.txt', '.cgh', '.mb'])
        debug('assets:src:%s' % build_deps)
        urn_mapping = mapping_table_obj['urnmapping']

        def _write_mapping_table():
            print '%i assets -> %s' % (len(urn_mapping), env['MAPPING_TABLE'])
            with open(env['APP_MAPPING_TABLE'], 'w') as f:
                json_dump(mapping_table_obj, f, separators=(',', ':'))

        # Write mapping table
        _write_mapping_table()

        longest = len(max(build_deps, key=len)) + 2
        def _log(src, dest, skipping=False):
            msg = '(skipping) ' if skipping else ''
            print '{0:-<{longest}}> {2}{1}'.format(src + ' ', dest, msg, longest=longest)

        metrics = dict(built=0, skipped=0, failed=0)
        def build(src):
            dest = build_deps[src]
            if path_exists(dest):
                _log(src, dest, True)
                metrics['skipped'] += 1
            else:
                _log(src, dest)
                success = build_asset(src, dest, env, options)
                if not success:
                    # Bit of a hack to remove the failed asset from the mapping table.
                    asset = src[len('assets/'):]
                    del urn_mapping[asset]
                    info('Removing asset from mapping table: %s' % asset)
                    metrics['failed'] += 1
                else:
                    metrics['built'] += 1

        class Builder(Thread):
            def __init__(self, assets):
                Thread.__init__(self)
                self.assets = assets

            def run(self):
                map(build, self.assets)

        assets = build_deps.keys()
        num_threads = int(options.threads)
        threads = [Builder(assets[i::num_threads]) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        else:
            del threads

        # Write mapping table
        _write_mapping_table()

        _log_stage("BUILT: %i - SKIPPED: %i - FAILED: %i" % (metrics['built'], metrics['skipped'], metrics['failed']))

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
                           code_base + ".canvas.default.debug.html",
                           code_base + ".canvas.default.release.html",
                           code_base + ".canvas.js",
                           code_base + ".debug.html",
                           code_base + ".release.html",
                           code_base + ".default.debug.html",
                           code_base + ".default.release.html",
                           code_base + ".tzjs" ]
            debug("code:dest:%s" % code_dests)

            for dest in code_dests:
                print '%s -> %s' % (src, dest)
                success = build_code(src, dest, env, options)
                if not success:
                    warning('failed')

    _log_stage('END')

    return 0

if __name__ == "__main__":
    exit(main())

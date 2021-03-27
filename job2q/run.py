# -*- coding: utf-8 -*-
import os
import sys
from time import sleep
from argparse import ArgumentParser, Action, SUPPRESS
from subprocess import check_output, CalledProcessError, STDOUT
from . import messages
from .readspec import readspec
from .utils import Bunch, DefaultItem, _, o, p, q, printree
from .fileutils import AbsPath, NotAbsolutePath, buildpath, dirbranches
from .shared import ArgList, names, environ, hostspecs, jobspecs, options
from .submit import setup, submit 

class LsOptions(Action):
    def __init__(self, **kwargs):
        super().__init__(nargs=0, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        if jobspecs.versions:
            print(_('Versiones del programa:'))
            printree([DefaultItem(i, jobspecs.defaults.version) for i in jobspecs.versions], level=1)
        for path in jobspecs.defaults.parameterpaths:
            tree = {}
            pathcomponents = AbsPath(path).setkeys(names).yieldcomponents()
            dirbranches(AbsPath(next(pathcomponents)), pathcomponents, jobspecs.defaults.parameters, tree)
            if tree:
               print(_('Parámetros en $path:'))
               printree(tree, level=1)
        if jobspecs.keywords:
            print(_('Variables de interpolación:'))
            printree([DefaultItem(i) for i in jobspecs.keywords], level=1)
        raise SystemExit()

class SetCwd(Action):
    def __init__(self, **kwargs):
        super().__init__(nargs=1, **kwargs)
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, AbsPath(values[0], cwd=os.getcwd()))

try:

    homedir = os.path.expanduser('~')
    parser = ArgumentParser(add_help=False)
    parser.add_argument('--specdir', metavar='SPECDIR', help='Ruta al directorio de especificaciones del programa.')
    parser.add_argument('--program', metavar='PROGNAME', help='Nombre estandarizado del programa.')
    parsedargs, remainingargs = parser.parse_known_args()
    globals().update(vars(parsedargs))
    
    try:
        environ.TELEGRAM_CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
    except KeyError:
        pass
    
    hostspecs.merge(readspec(buildpath(specdir, program, 'hostspecs.json')))
    hostspecs.merge(readspec(buildpath(specdir, program, 'queuespecs.json')))

    jobspecs.merge(readspec(buildpath(specdir, program, 'packagespecs.json')))
    jobspecs.merge(readspec(buildpath(specdir, program, 'packageconf.json')))
    
    userspecdir = buildpath(homedir, '.jobspecs', program + '.json')
    
    if os.path.isfile(userspecdir):
        jobspecs.merge(readspec(userspecdir))
    
    try: names.cluster = hostspecs.clustername
    except AttributeError:
        messages.error('No se definió el nombre del clúster', spec='clustername')

    try: names.head = hostspecs.headname
    except AttributeError:
        messages.error('No se definió el nombre del nodo maestro', spec='clustername')

    parser = ArgumentParser(prog=program, add_help=False, description='Envía trabajos de {} a la cola de ejecución.'.format(jobspecs.packagename))

    group0 = parser.add_argument_group('Argumentos')
    group0.add_argument('fileargs', nargs='*', metavar='FILE', help='Ruta al acrhivo de entrada.')

    group1 = parser.add_argument_group('Ejecución remota')
    group1.add_argument('-H', '--remotehost', metavar='HOSTNAME', help='Procesar el trabajo en el host HOSTNAME.')

    group2 = parser.add_argument_group('Opciones comunes')
    group2.key = 'common'
    group2.add_argument('-h', '--help', action='help', help='Mostrar este mensaje de ayuda y salir.')
    group2.add_argument('-l', '--list', action=LsOptions, default=SUPPRESS, help='Mostrar las opciones disponibles y salir.')
    group2.add_argument('-v', '--version', metavar='PROGVERSION', default=SUPPRESS, help='Versión del ejecutable.')
    group2.add_argument('-q', '--queue', metavar='QUEUENAME', default=SUPPRESS, help='Nombre de la cola requerida.')
    group2.add_argument('-n', '--nproc', type=int, metavar='#PROCS', default=1, help='Número de núcleos de procesador requeridos.')
    group2.add_argument('-w', '--wait', type=float, metavar='TIME', default=SUPPRESS, help='Tiempo de pausa (en segundos) después de cada ejecución.')
    group2.add_argument('-f', '--filter', metavar='REGEX', default=SUPPRESS, help='Enviar únicamente los trabajos que coinciden con la expresión regular.')
    group2.add_argument('-d', '--ignore-defaults', action='store_true', help='Ignorar las versiones por defecto de lo programas y parámetros.')
    group2.add_argument('-o', '--outdir', metavar='JOBDIR', default=SUPPRESS, help='Escribir los archivos de salida en el directorio JOBDIR.')
    group2.add_argument('-b', '--base', action='store_true', help='Interpretar los argumentos como nombres de trabajos.')
    group2.add_argument('-i', '--interpolate', action='store_true', help='Interpolar los archivos de entrada.')
    group2.add_argument('-p', '--prefix', metavar='PREFIX', default=SUPPRESS, help='Agregar el prefijo PREFIX al nombre del trabajo.')
    group2.add_argument('-s', '--suffix', metavar='SUFFIX', default=SUPPRESS, help='Agregar el sufijo SUFFIX al nombre del trabajo.')
    group2.add_argument('-S', '--sort', metavar='ORDER', default=SUPPRESS, help='Ordenar los argumentos de acuerdo al orden ORDER.')
    group2.add_argument('-a', '--addpath', metavar='PATH', action='append', default=[], help='Agregar la ruta de parámetros PATH.')
    group2.add_argument('--root', action=SetCwd, metavar='ROOTDIR', default=os.getcwd(), help='Usar rutas relativas al directorio ROOTDIR.')
    group2.add_argument('--scratch', metavar='SCRDIR', default=SUPPRESS, help='Escribir los archivos temporales en el directorio SCRDIR.')
    group2.add_argument('--delete', action='store_true', help='Borrar los archivos de entrada después de enviar el trabajo.')
    group2.add_argument('--dry', action='store_true', help='Procesar los archivos de entrada sin enviar el trabajo.')
#    group2.add_argument('-X', '--xdialog', action='store_true', help='Habilitar el modo gráfico para los mensajes y diálogos.')

    molgroup = group2.add_mutually_exclusive_group()
    molgroup.add_argument('-m', '--addmol', metavar='MOLFILE', action='append', default=[], help='Agregar el paso final del archivo MOLFILE a las coordenadas de interpolación.')
    molgroup.add_argument('-M', '--allmol', metavar='MOLFILE', default=SUPPRESS, help='Usar todos los pasos del archivo MOLFILE como coordenadas de interpolación.')

    hostgroup = group2.add_mutually_exclusive_group()
    hostgroup.add_argument('-N', '--nhost', type=int, metavar='#NODES', default=SUPPRESS, help='Número de nodos de ejecución requeridos.')
    hostgroup.add_argument('--hosts', metavar='NODELIST', default=SUPPRESS, help='Solicitar nodos específicos de ejecución por nombre.')

    yngroup = group2.add_mutually_exclusive_group()
    yngroup.add_argument('--yes', '--si', action='store_true', help='Responder "si" a todas las preguntas.')
    yngroup.add_argument('--no', action='store_true', help='Responder "no" a todas las preguntas.')

    group3 = parser.add_argument_group('Conjuntos de parámetros')
    group3.key = 'parameters'
    for key in jobspecs.parameters:
        group3.add_argument(o(key), metavar='PARAMETERSET', default=SUPPRESS, help='Nombre del conjunto de parámetros.')

    group4 = parser.add_argument_group('Archivos opcionales')
    group4.key = 'fileopts'
    for key, value in jobspecs.fileopts.items():
        group4.add_argument(o(key), metavar='FILEPATH', default=SUPPRESS, help='Ruta al archivo {}.'.format(value))

    group5 = parser.add_argument_group('Variables de interpolación')
    group5.key = 'keywords'
    for key in jobspecs.keywords:
        group5.add_argument(o(key), metavar=key.upper(), default=SUPPRESS, help='Valor de la variable {}.'.format(key.upper()))

    parsedargs = parser.parse_args(remainingargs)

    for group in parser._action_groups:
        if hasattr(group, 'key'):
            group_dict = {a.dest:getattr(parsedargs, a.dest) for a in group._group_actions if a.dest in parsedargs}
            setattr(options, group.key, Bunch(**group_dict))

    if parsedargs.fileargs:
        arglist = ArgList(parsedargs.fileargs)
    else:
        messages.error('Debe especificar al menos un archivo de entrada')

    for key in options.fileopts:
        options.fileopts[key] = AbsPath(options.fileopts[key], cwd=options.common.root)
        if not options.fileopts[key].isfile():
            messages.error('El archivo de entrada', options.fileopts[key], 'no existe', option=o(key))

    if parsedargs.remotehost:

        filelist = []
        remotejobs = []
        remotehost = parsedargs.remotehost
        userhost = names.user + '@' + names.host
        try:
            output = check_output(['ssh', remotehost, 'echo $JOBSHARE'], stderr=STDOUT)
        except CalledProcessError as exc:
            messages.error(exc.output.decode(sys.stdout.encoding).strip())
        remoteshare = output.decode(sys.stdout.encoding).strip()
        if not remoteshare:
            messages.error('El servidor remoto no acepta trabajos de otro servidor')
        #TODO: Consider include common.addmol path in fileopts
        if 'mol' in options.common:
            filelist.append(buildpath(homedir, '.', os.path.relpath(options.common.addmol, homedir)))
        #DONE?: Make default empty dict for fileopts so no test is needed
        for item in options.fileopts.values():
            filelist.append(buildpath(homedir, '.', os.path.relpath(item, homedir)))
        for item in arglist:
            rootdir, basename = item
            relparent = os.path.relpath(rootdir, homedir)
            remotecwd = buildpath(remoteshare, userhost, relparent)
            remotejobs.append(basename)
            for key in jobspecs.filekeys:
                if os.path.isfile(buildpath(rootdir, (basename, key))):
                    filelist.append(buildpath(homedir, '.', relparent, (basename, key)))
        if remotejobs:
            options.switch.add('base')
            options.switch.add('delete')
            options.define.update({'root': remotecwd})
            try:
                check_output(['rsync', '-qRLtz'] + filelist + [remotehost + ':' + buildpath(remoteshare, userhost)])
            except CalledProcessError as exc:
                messages.error(exc.output.decode(sys.stdout.encoding).strip())
            os.execv('/usr/bin/ssh', [__file__, '-qt', remotehost] + [env + '=' + val for env, val in environ.items()] + [program] + [o(opt) for opt in options.switch] + [o(opt, val) for opt, val in options.define.items()] + [o(opt, val) for opt, valist in options.append.items() for val in valist] + remotejobs)
        raise SystemExit()

    else:

        setup()
        options.interpolate()

        try:
            rootdir, basename = next(arglist)
        except StopIteration:
            sys.exit()

        submit(rootdir, basename)
        for rootdir, basename in arglist:
            sleep(options.common.wait)
            submit(rootdir, basename)
    
except KeyboardInterrupt:
    messages.error('Interrumpido por el usuario')


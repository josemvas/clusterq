# -*- coding: utf-8 -*-
import os
import sys
from subprocess import check_output, CalledProcessError
from .details import wrappers
from . import dialogs, messages
from .queue import jobsubmit, jobstat
from .fileutils import AbsPath, NotAbsolutePath, formatpath, remove
from .utils import Bunch, IdentityList, natkey, o, p, q, Q, join_args, booldict, interpolate
from .shared import names, paths, environ, clusterspecs, jobspecs, options, remoteargs
from .parsing import BoolParser
from .readmol import readmol

parameterpaths = []
script = Bunch()

def initialize():

    script.main = []
    script.setup = []
    script.header = []
    script.envars = []

    for key, path in options.targetfiles.items():
        if not path.isfile():
            messages.error('El archivo de entrada', path, 'no existe', option=o(key))

    if options.remote.host:
        paths.socketdir = AbsPath(formatpath(paths.home, '.ssh', 'job2q'))
        paths.socket = paths.socketdir / options.remote.host
        paths.socketdir.makedirs()
        try:
            environment = check_output(['ssh', '-o', 'ControlMaster=auto', '-o', 'ControlPersist=60', '-S', paths.socket, options.remote.host, 'printenv JOBCOMMAND JOBSYNCDIR'])
        except CalledProcessError as e:
            messages.error(e.output.decode(sys.stdout.encoding).strip())
        options.remote.cmd, options.remote.root = environment.decode(sys.stdout.encoding).splitlines()
        if 'cmd' not in options.remote and 'root' not in options.remote:
            messages.error('El servidor no está configurado para aceptar trabajos')
        if 'cmd' not in options.remote or 'root' not in options.remote:
            messages.error('El servidor no está correctamente configurado para aceptar trabajos')

    if options.interpolation.vars or options.interpolation.mol or 'trjmol' in options.interpolation:
        options.interpolation.interpolate = True
    else:
        options.interpolation.interpolate = False

    if options.interpolation.interpolate:
        options.interpolation.list = []
        options.interpolation.dict = {}
        if options.interpolation.vars:
            for var in options.interpolation.vars:
                left, separator, right = var.partition('=')
                if separator:
                    if right:
                        options.interpolation.dict[left] = right
                    else:
                        messages.error('No se especificó ningín valor para la variable de interpolación', left)
                else:
                    options.interpolation.list.append(left)
        if options.interpolation.mol:
            index = 0
            for path in options.interpolation.mol:
                index += 1
                path = AbsPath(path, cwd=options.common.cwd)
                coords = readmol(path)[-1]
                options.interpolation.dict['mol' + str(index)] = '\n'.join('{0:<2s}  {1:10.4f}  {2:10.4f}  {3:10.4f}'.format(*atom) for atom in coords)
            if not 'prefix' in options.interpolation:
                if len(options.interpolation.mol) == 1:
                    options.prefix = path.stem
                else:
                    messages.error('Se debe especificar un prefijo cuando se especifican múltiples archivos de coordenadas')
        elif 'trjmol' in options.interpolation:
            index = 0
            path = AbsPath(options.common.molall, cwd=options.common.cwd)
            for coords in readmol(path):
                index += 1
                options.interpolation.dict['mol' + str(index)] = '\n'.join('{0:<2s}  {1:10.4f}  {2:10.4f}  {3:10.4f}'.format(*atom) for atom in coords)
            if not 'prefix' in options.interpolation:
                options.prefix = path.stem
        else:
            if not 'prefix' in options.interpolation and not 'suffix' in options.interpolation:
                messages.error('Se debe especificar un prefijo o un sufijo para interpolar sin archivo coordenadas')

    if options.common.defaults:
        jobspecs.defaults.pop('version', None)
        jobspecs.defaults.pop('parameterset', None)
    
    if 'wait' not in options.common:
        try:
            options.common.wait = float(clusterspecs.defaults.wait)
        except AttributeError:
            options.common.wait = 0
    
    if 'nodes' not in options.common:
        options.common.nodes = 1

#TODO Add suport for dialog boxes
#    if options.common.xdialog:
#        try:
#            from tkdialog import TkDialog
#        except ImportError:
#            raise SystemExit()
#        else:
#            dialogs.yesno = join_args(TkDialog().yesno)
#            messages.failure = join_args(TkDialog().message)
#            messages.success = join_args(TkDialog().message)

    if not 'scratch' in clusterspecs.defaults:
        messages.error('No se especificó el directorio de escritura por defecto', spec='defaults.scratch')

    if 'scratch' in options.common:
        options.jobscratch = options.common.scratch / clusterspecs.envars.jobid
    else:
        options.jobscratch = AbsPath(formatpath(clusterspecs.defaults.scratch, keys=names)) / clusterspecs.envars.jobid

    if 'queue' not in options.common:
        if 'queue' in clusterspecs.defaults:
            options.common.queue = clusterspecs.defaults.queue
        else:
            messages.error('Debe especificar la cola a la que desea enviar el trabajo')
    
    if not 'packagename' in jobspecs:
        messages.error('No se especificó el nombre del programa', spec='packagename')
    
    if not 'shortname' in jobspecs:
        messages.error('No se especificó el sufijo del programa', spec='shortname')
    
    for key in options.parameters:
        if '/' in options.parameters[key]:
            messages.error(options.parameters[key], 'no puede ser una ruta', option=key)

    if 'mpilaunch' in jobspecs:
        try: jobspecs.mpilaunch = booldict[jobspecs.mpilaunch]
        except KeyError:
            messages.error('Este valor requiere ser "True" o "False"', spec='mpilaunch')
    
    if not jobspecs.filekeys:
        messages.error('La lista de archivos del programa no existe o está vacía', spec='filekeys')
    
    if jobspecs.inputfiles:
        for key in jobspecs.inputfiles:
            if not key in jobspecs.filekeys:
                messages.error('La clave', q(key), 'no tiene asociado ningún archivo', spec='inputfiles')
    else:
        messages.error('La lista de archivos de entrada no existe o está vacía', spec='inputfiles')
    
    if jobspecs.outputfiles:
        for key in jobspecs.outputfiles:
            if not key in jobspecs.filekeys:
                messages.error('La clave', q(key), 'no tiene asociado ningún archivo', spec='outputfiles')
    else:
        messages.error('La lista de archivos de salida no existe o está vacía', spec='outputfiles')

    if 'jobkind' in clusterspecs:
        script.header.append(clusterspecs.jobkind.format(jobspecs.packagename))

    #TODO MPI support for Slurm
    if jobspecs.parallelib:
        if jobspecs.parallelib.lower() == 'none':
            if 'nodelist' in options.common:
                for item in clusterspecs.serialat:
                    script.header.append(item.format(**options.common))
            else:
                for item in clusterspecs.serial:
                    script.header.append(item.format(**options.common))
        elif jobspecs.parallelib.lower() == 'openmp':
            if 'nodelist' in options.common:
                for item in clusterspecs.singlehostat:
                    script.header.append(item.format(**options.common))
            else:
                for item in clusterspecs.singlehost:
                    script.header.append(item.format(**options.common))
            script.main.append('OMP_NUM_THREADS=' + str(options.common.nproc))
        elif jobspecs.parallelib.lower() == 'standalone':
            if 'nodelist' in options.common:
                for item in clusterspecs.multihostat:
                    script.header.append(item.format(**options.common))
            else:
                for item in clusterspecs.multihost:
                    script.header.append(item.format(**options.common))
        elif jobspecs.parallelib.lower() in wrappers:
            if 'nodelist' in options.common:
                for item in clusterspecs.multihostat:
                    script.header.append(item.format(**options.common))
            else:
                for item in clusterspecs.multihost:
                    script.header.append(item.format(**options.common))
            script.main.append(clusterspecs.mpilauncher[jobspecs.parallelib])
        else:
            messages.error('El tipo de paralelización', jobspecs.parallelib, 'no está soportado', spec='parallelib')
    else:
        messages.error('No se especificó el tipo de paralelización del programa', spec='parallelib')
    
    if jobspecs.versions:
        if 'version' not in options.common:
            if 'version' in jobspecs.defaults:
                if jobspecs.defaults.version in jobspecs.versions:
                    options.common.version = jobspecs.defaults.version
                else:
                    messages.error('La versión establecida por defecto es inválida', spec='defaults.version')
            else:
                options.common.version = dialogs.chooseone('Seleccione una versión', choices=sorted(jobspecs.versions.keys(), key=natkey))
        if options.common.version not in jobspecs.versions:
            messages.error('La versión', options.common.version, 'no es válida', option='version')
    else:
        messages.error('La lista de versiones no existe o está vacía', spec='versions')

    if not jobspecs.versions[options.common.version].executable:
        messages.error('No se especificó el ejecutable', spec='versions[{}].executable'.format(options.common.version))
    
    for envar, path in jobspecs.export.items() | jobspecs.versions[options.common.version].export.items():
        abspath = AbsPath(formatpath(path, keys=names), cwd=options.jobscratch)
        script.setup.append('export {0}={1}'.format(envar, abspath))

    for envar, path in jobspecs.append.items() | jobspecs.versions[options.common.version].append.items():
        abspath = AbsPath(formatpath(path, keys=names), cwd=options.jobscratch)
        script.setup.append('{0}={1}:${0}'.format(envar, abspath))

    for path in jobspecs.source + jobspecs.versions[options.common.version].source:
        script.setup.append('source {}'.format(AbsPath(formatpath(path, keys=names))))

    if jobspecs.load or jobspecs.versions[options.common.version].load:
        script.setup.append('module purge')

    for module in jobspecs.load + jobspecs.versions[options.common.version].load:
        script.setup.append('module load {}'.format(module))

    try:
        script.main.append(AbsPath(formatpath(jobspecs.versions[options.common.version].executable, keys=names)))
    except NotAbsolutePath:
        script.main.append(jobspecs.versions[options.common.version].executable)

    for path in clusterspecs.logfiles:
        script.header.append(path.format(AbsPath(formatpath(clusterspecs.logdir, keys=names))))

    script.setup.append("shopt -s nullglob extglob")

    script.setenv = '{}="{}"'.format

    script.envars.extend(clusterspecs.envars.items())
    script.envars.extend((k + 'name', v) for k, v in names.items())
    script.envars.extend((k, jobspecs.filekeys[v]) for k, v in jobspecs.filevars.items())

    script.envars.append(("freeram", "$(free -m | tail -n+3 | head -1 | awk '{print $4}')"))
    script.envars.append(("totalram", "$(free -m | tail -n+2 | head -1 | awk '{print $2}')"))
    script.envars.append(("jobram", "$(($nproc*$totalram/$(nproc --all)))"))

    for key in jobspecs.optargs:
        if not jobspecs.optargs[key] in jobspecs.filekeys:
            messages.error('La clave', q(key) ,'no tiene asociado ningún archivo', spec='optargs')
        script.main.append('-{key} {val}'.format(key=key, val=jobspecs.filekeys[jobspecs.optargs[key]]))
    
    for item in jobspecs.posargs:
        for key in item.split('|'):
            if not key in jobspecs.filekeys:
                messages.error('La clave', q(key) ,'no tiene asociado ningún archivo', spec='posargs')
        script.main.append('@' + p('|'.join(jobspecs.filekeys[i] for i in item.split('|'))))
    
    if 'stdinput' in jobspecs:
        try:
            script.main.append('0<' + ' ' + jobspecs.filekeys[jobspecs.stdinput])
        except KeyError:
            messages.error('La clave', q(jobspecs.stdinput) ,'no tiene asociado ningún archivo', spec='stdinput')
    if 'stdoutput' in jobspecs:
        try:
            script.main.append('1>' + ' ' + jobspecs.filekeys[jobspecs.stdoutput])
        except KeyError:
            messages.error('La clave', q(jobspecs.stdoutput) ,'no tiene asociado ningún archivo', spec='stdoutput')
    if 'stderror' in jobspecs:
        try:
            script.main.append('2>' + ' ' + jobspecs.filekeys[jobspecs.stderror])
        except KeyError:
            messages.error('La clave', q(jobspecs.stderror) ,'no tiene asociado ningún archivo', spec='stderror')
    
    script.chdir = 'cd "{}"'.format
    if clusterspecs.filesync == 'local':
        script.rmdir = 'rm -rf "{}"'.format
        script.mkdir = 'mkdir -p -m 700 "{}"'.format
        if options.common.dispose:
            script.simport = 'mv "{}" "{}"'.format
        else:
            script.simport = 'cp "{}" "{}"'.format
        script.rimport = 'cp -r "{}/." "{}"'.format
        script.sexport = 'cp "{}" "{}"'.format
    elif clusterspecs.filesync == 'remote':
        script.rmdir = 'for host in ${{hostlist[*]}}; do rsh $host rm -rf "\'{}\'"; done'.format
        script.mkdir = 'for host in ${{hostlist[*]}}; do rsh $host mkdir -p -m 700 "\'{}\'"; done'.format
        if options.common.dispose:
            script.simport = 'for host in ${{hostlist[*]}}; do rcp $headname:"\'{0}\'" $host:"\'{1}\'" && rsh $headname rm "\'{0}\'"; done'.format
        else:
            script.simport = 'for host in ${{hostlist[*]}}; do rcp $headname:"\'{0}\'" $host:"\'{1}\'"; done'.format
        script.rimport = 'for host in ${{hostlist[*]}}; do rsh $headname tar -cf- -C "\'{0}\'" . | rsh $host tar -xf- -C "\'{1}\'"; done'.format
        script.sexport = 'rcp "{}" $headname:"\'{}\'"'.format
    elif clusterspecs.filesync == 'secure':
        script.rmdir = 'for host in ${{hostlist[*]}}; do ssh $host rm -rf "\'{}\'"; done'.format
        script.mkdir = 'for host in ${{hostlist[*]}}; do ssh $host mkdir -p -m 700 "\'{}\'"; done'.format
        if options.common.dispose:
            script.simport = 'for host in ${{hostlist[*]}}; do scp $headname:"\'{0}\'" $host:"\'{1}\'" && ssh $headname rm "\'{0}\'"; done'.format
        else:
            script.simport = 'for host in ${{hostlist[*]}}; do scp $headname:"\'{0}\'" $host:"\'{1}\'"; done'.format
        script.rimport = 'for host in ${{hostlist[*]}}; do ssh $headname tar -cf- -C "\'{0}\'" . | ssh $host tar -xf- -C "\'{1}\'"; done'.format
        script.sexport = 'scp "{}" $headname:"\'{}\'"'.format
    else:
        messages.error('El método de copia', q(clusterspecs.filesync), 'no es válido', spec='filesync')

    parameterdict = {}
    parameterdict.update(jobspecs.defaults.parameters)
    parameterdict.update(options.parameters)

#    #TODO Move this code to the submit function
#    #TODO Use filter groups to set parameters
#    for key, value in options.parameterdict.items():
#        if value.startswith('%'):
#            try:
#                index = int(value[1:]) - 1
#            except ValueError:
#                messages.error(value, 'debe tener un índice numérico', option=o(key))
#            if index not in range(len(filtergroups)):
#                messages.error(value, 'El índice está fuera de rango', option=o(key))
#            parameterdict.update({key: filtergroups[index]})

    for path in jobspecs.defaults.parameterpaths:
        partlist = AbsPath(formatpath(path, keys=names), cwd=options.common.cwd).parts
        rootpath = AbsPath(next(partlist))
        for part in partlist:
            try:
                rootpath = rootpath / interpolate(part, keydict=parameterdict)
            except ValueError as e:
                messages.error('Hay variables de interpolación inválidas en la ruta', path, var=e.args[0])
            except KeyError:
                choices = rootpath.listdir()
                choice = dialogs.chooseone('Seleccione una opción', choices=choices)
                rootpath = rootpath / choice
        if rootpath.exists():
            parameterpaths.append(rootpath)
        else:
            messages.error('La ruta', path, 'no existe', spec='defaults:parameterpaths')

    if 'prefix' in options.interpolation:
        try:
            options.prefix = interpolate(
                options.interpolation.prefix,
                keylist=options.interpolation.list,
                keydict=options.interpolation.dict,
            )
        except ValueError as e:
            messages.error('Hay variables de interpolación inválidas en el prefijo', opt='--prefix', var=e.args[0])
        except (IndexError, KeyError) as e:
            messages.error('Hay variables de interpolación sin definir en el prefijo', opt='--prefix', var=e.args[0])

    if 'suffix' in options.interpolation:
        try:
            options.suffix = interpolate(
                options.interpolation.suffix,
                keylist=options.interpolation.list,
                keydict=options.interpolation.dict,
            )
        except ValueError as e:
            messages.error('Hay variables de interpolación inválidas en el sufijo', opt='--suffix', var=e.args[0])
        except (IndexError, KeyError) as e:
            messages.error('Hay variables de interpolación sin definir en el sufijo', opt='--suffix', var=e.args[0])


def submit(parentdir, inputname):

    filebools = {key: AbsPath(formatpath(parentdir, (inputname, key))).isfile() or key in options.targetfiles for key in jobspecs.filekeys}
    for conflict, message in jobspecs.conflicts.items():
        if BoolParser(conflict).evaluate(filebools):
            messages.error(message, p(inputname))

    if inputname.endswith('.' + jobspecs.shortname):
        jobname = inputname[:-len(jobspecs.shortname)-1]
    else:
        jobname = inputname

    if 'prefix' in options:
        jobname = options.prefix + '.' + jobname

    if 'suffix' in options:
        jobname = jobname +  '.' + options.suffix

    #TODO Append program version to output file extension if option is enabled
    if inputname.endswith('.' + jobspecs.shortname):
        outputname = jobname + '.' + jobspecs.shortname
    else:
        outputname = jobname

    if 'out' in options.common:
        outdir = AbsPath(options.common.out, cwd=parentdir)
    else:
        outdir = AbsPath(jobname, cwd=parentdir)

    rawfiles = {}
    interpolated = {}

    if options.common.raw:
        stagedir = parentdir
    else:
        if outdir == parentdir:
            messages.failure('El directorio de salida debe ser distinto al directorio padre')
            return
        stagedir = outdir
        for key in jobspecs.inputfiles:
            srcpath = AbsPath(formatpath(parentdir, (inputname, key)))
            destpath = formatpath(stagedir, (outputname, key))
            if srcpath.isfile():
                if 'interpolable' in jobspecs and key in jobspecs.interpolable:
                    with open(srcpath, 'r') as f:
                        contents = f.read()
                        if options.interpolation.interpolate:
                            try:
                                interpolated[destpath] = interpolate(
                                    contents,
                                    keylist=options.interpolation.list,
                                    keydict=options.interpolation.dict,
                                )
                            except ValueError:
                                messages.failure('Hay variables de interpolación inválidas en el archivo de entrada', file=formatpath((inputname, key)))
                                return
                            except (IndexError, KeyError) as e:
                                messages.failure('Hay variables de interpolación sin definir en el archivo de entrada', file=formatpath((inputname, key)), key=e.args[0])
                                return
                        else:
                            try:
                                interpolated[destpath] = interpolate(contents)
                            except ValueError:
                                pass
                            except (IndexError, KeyError) as e:
                                if dialogs.yesno('Parece que hay variables de interpolación en el archivo de entrada', formatpath((inputname, key)),'¿desea continuar sin interpolar?'):
                                    rawfiles[destpath] = srcpath
                                else:
                                    return
                else:
                    rawfiles[destpath] = srcpath

    jobdir = AbsPath(formatpath(stagedir, (jobname, jobspecs.shortname + '.'.join(options.common.version.split()))))

    if outdir.isdir():
        if jobdir.isdir():
            try:
                with open(formatpath(jobdir, 'jobid'), 'r') as f:
                    jobid = f.read()
                jobstate = jobstat(jobid)
                if jobstate is not None:
                    messages.failure(jobstate.format(id=jobid, name=jobname))
                    return
            except FileNotFoundError:
                pass
        if not set(outdir.listdir()).isdisjoint(formatpath((outputname, k)) for k in jobspecs.outputfiles):
            if options.common.no or (not options.common.yes and not dialogs.yesno('Si corre este cálculo los archivos de salida existentes en el directorio', outdir,'serán sobreescritos, ¿desea continuar de todas formas?')):
                messages.failure('Cancelado por el usuario')
                return
        for key in jobspecs.outputfiles:
            remove(formatpath(outdir, (outputname, key)))
        if parentdir != outdir:
            for key in jobspecs.inputfiles:
                remove(formatpath(outdir, (outputname, key)))
    else:
        try:
            outdir.makedirs()
        except FileExistsError:
            messages.failure('No se puede crear la carpeta', outdir, 'porque ya existe un archivo con ese nombre')
            return

    for destpath, literalfile in rawfiles.items():
        literalfile.copyto(destpath)

    for destpath, contents in interpolated.items():
        with open(destpath, 'w') as f:
            f.write(contents)

    for key, targetfile in options.targetfiles.items():
        targetfile.linkto(formatpath(stagedir, (outputname, jobspecs.fileoptions[key])))

    if options.remote.host:

        reloutdir = os.path.relpath(outdir, paths.home)
        remotehome = formatpath(options.remote.root, (names.user, names.host))
        remotetemp = formatpath(options.remote.root, (names.user, names.host, 'temp'))
        remoteargs.switches.add('raw')
        remoteargs.switches.add('jobargs')
        remoteargs.switches.add('dispose')
        remoteargs.constants.update({'cwd': formatpath(remotetemp, reloutdir)})
        remoteargs.constants.update({'out': formatpath(remotehome, reloutdir)})
        filelist = []
        for key in jobspecs.filekeys:
            if os.path.isfile(formatpath(outdir, (outputname, key))):
                filelist.append(formatpath(paths.home, '.', reloutdir, (outputname, key)))
        arglist = [__file__, '-qt', '-S', paths.socket, options.remote.host]
        arglist.extend(env + '=' + val for env, val in environ.items())
        arglist.append(options.remote.cmd)
        arglist.append(names.program)
        arglist.extend(o(opt) for opt in remoteargs.switches)
        arglist.extend(o(opt, Q(val)) for opt, val in remoteargs.constants.items())
        arglist.extend(o(opt, Q(val)) for opt, lst in remoteargs.lists.items() for val in lst)
        arglist.append(jobname)
        if options.debug.dryrun:
            print('<FILE LIST>', ' '.join(filelist), '</FILE LIST>')
            print('<COMMAND LINE>', ' '.join(arglist[3:]), '</COMMAND LINE>')
        else:
            try:
                check_output(['rsync', '-qRLtz', '-e', 'ssh -S {}'.format(paths.socket)] + filelist + [options.remote.host + ':' + remotetemp])
                check_output(['rsync', '-qRLtz', '-f', '-! */', '-e', 'ssh -S {}'.format(paths.socket)] + filelist + [options.remote.host + ':' + remotehome])
            except CalledProcessError as e:
                messages.error(e.output.decode(sys.stdout.encoding).strip())
            os.execv('/usr/bin/ssh', arglist)

    else:

        imports = []
        exports = []
    
        for key in jobspecs.inputfiles:
            if AbsPath(formatpath(parentdir, (inputname, key))).isfile():
                imports.append(script.simport(formatpath(stagedir, (outputname, key)), formatpath(options.jobscratch, jobspecs.filekeys[key])))
    
        for key in options.targetfiles:
            imports.append(script.simport(formatpath(stagedir, (outputname, jobspecs.fileoptions[key])), formatpath(options.jobscratch, jobspecs.filekeys[jobspecs.fileoptions[key]])))
    
        for path in parameterpaths:
            if path.isfile():
                imports.append(script.simport(path, formatpath(options.jobscratch, path.name)))
            elif path.isdir():
                imports.append(script.rimport(formatpath(path), options.jobscratch))
    
        for key in jobspecs.outputfiles:
            exports.append(script.sexport(formatpath(options.jobscratch, jobspecs.filekeys[key]), formatpath(outdir, (outputname, key))))

        try:
            jobdir.mkdir()
        except FileExistsError:
            messages.failure('No se puede crear la carpeta', jobdir, 'porque ya existe un archivo con ese nombre')
            return

        jobscript = formatpath(jobdir, 'jobscript')

        with open(jobscript, 'w') as f:
            f.write('#!/bin/bash' + '\n')
            f.write(clusterspecs.jobname.format(jobname) + '\n')
            f.write(''.join(i + '\n' for i in script.header))
            f.write(''.join(i + '\n' for i in script.setup))
            f.write(''.join(script.setenv(i, j) + '\n' for i, j in script.envars))
            f.write(script.setenv('jobname', jobname) + '\n')
            f.write('for host in ${hostlist[*]}; do echo "<$host>"; done' + '\n')
            f.write(script.mkdir(options.jobscratch) + '\n')
            f.write(''.join(i + '\n' for i in imports))
            f.write(script.chdir(options.jobscratch) + '\n')
            f.write(''.join(i + '\n' for i in jobspecs.prescript))
            f.write(' '.join(script.main) + '\n')
            f.write(''.join(i + '\n' for i in jobspecs.postscript))
            f.write(''.join(i + '\n' for i in exports))
            f.write(script.rmdir(options.jobscratch) + '\n')
            f.write(''.join(i + '\n' for i in clusterspecs.offscript))
    
        if options.debug.dryrun:
            messages.success('Se procesó el trabajo', q(jobname), 'y se generaron los archivos para el envío en', jobdir)
        else:
            try:
                jobid = jobsubmit(jobscript)
            except RuntimeError as error:
                messages.failure('El gestor de trabajos reportó un error al enviar el trabajo', q(jobname), p(error))
                return
            else:
                messages.success('El trabajo', q(jobname), 'se correrá en', str(options.common.nproc), 'núcleo(s) en', names.cluster, 'con número de trabajo', jobid)
                with open(formatpath(jobdir, 'jobid'), 'w') as f:
                    f.write(jobid)
    

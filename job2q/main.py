# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from __future__ import print_function
from __future__ import absolute_import
from __future__ import division

import os
import sys
import errno
from os.path import dirname, basename, realpath, isdir, isfile
from os import listdir, chmod
from importlib import reload

from job2q.dialogs import dialogs
from job2q.messages import messages
from job2q.utils import rmdir, makedirs, copyfile, hardlink, pathjoin, pathexpand
from job2q.strings import consoleScript
from job2q.parsing import parsexml

def run():
    import job2q.getconf
    while job2q.getconf.userconf.inputlist:
        try:
            if 'job2q.submit' in sys.modules:
                sleep(job2q.getconf.jobconf.waitime)
                reload(job2q.submit)
            else:
                import job2q.submit
        except KeyboardInterrupt:
            dialogs.error('Cancelado por el usario')
        except RuntimeError:
            pass

def setup(**kwargs):

    etcdir = kwargs['etcdir'] if 'etcdir' in kwargs else dialogs.path('Escriba la ruta donde se instalará la configuración (o deje vacío para omitir)')
    bindir = kwargs['bindir'] if 'bindir' in kwargs else dialogs.path('Escriba la ruta donde se instalarán los scripts configurados (o deje vacío para omitir)')

    sourcedir = dirname(realpath(__file__))
    genericdir = pathjoin(sourcedir, 'database', 'generic')
    platformdir = pathjoin(sourcedir, 'database', 'platform')

    hostname = kwargs['hostname'] if 'hostname' in kwargs else dialogs.optone('Seleccione la opción con la arquitectura más adecuada', choices=sorted(listdir(platformdir)))

    if not isfile(pathjoin(platformdir, hostname, 'hostspecs.xml')):
        messages.cfgerr('El archivo de configuración del host', hostname, 'no existe')

    if etcdir and isdir(etcdir):
        specdir = pathjoin(etcdir, 'j2q')
        if isfile(pathjoin(specdir, 'hostspecs.xml')):
            if dialogs.yesno('El sistema ya está configurado, ¿quiere reestablecer la configuración por defecto (si/no)?'):
                copyfile(pathjoin(platformdir, hostname, 'hostspecs.xml'), pathjoin(specdir, 'hostspecs.xml'))
        else:
            makedirs(specdir)
            copyfile(pathjoin(platformdir, hostname, 'hostspecs.xml'), pathjoin(specdir, 'hostspecs.xml'))
             
        available = { }
        configured = [ ]
    
        for package in listdir(pathjoin(platformdir, hostname)):
            if isdir(pathjoin(platformdir, hostname, package)):
                try:
                    title = parsexml(pathjoin(genericdir, package, 'jobspecs.xml'), 'title')
                except AttributeError:
                    messages.cfgerr('El archivo', pathjoin(genericdir, package, 'jobspecs.xml'), 'no tiene un título')
                available[title] = package
                if isfile(pathjoin(specdir, package, 'jobspecs.xml')):
                    configured.append(title)
    
        packagelist = list(available)
    
        if not packagelist:
            messages.warning('No hay paquetes configurados para este host')
            return
    
        selected = dialogs.optany('Seleccione los paquetes que desea configurar o reconfigurar', choices=packagelist, default=configured)

        if set(selected).isdisjoint(configured) or dialogs.yesno('Algunos de los paquetes seleccionados ya están configurados, ¿está seguro que quiere restablecer sus configuraciones por defecto (si/no)?'):
            for package in selected:
                makedirs(pathjoin(specdir, available[package]))
                hardlink(pathjoin(specdir, 'hostspecs.xml'), pathjoin(specdir, available[package], 'hostspecs.xml'))
                copyfile(pathjoin(genericdir, available[package], 'jobspecs.xml'), pathjoin(specdir, available[package], 'corespecs.xml'))
                copyfile(pathjoin(platformdir, hostname, available[package], 'jobspecs.xml'), pathjoin(specdir, available[package], 'customspecs.xml'))

    if bindir and isdir(bindir):
        for package in listdir(specdir):
            if isdir(pathjoin(specdir, package)):
                try:
                    with open(pathjoin(bindir, package), 'w') as fh:
                        fh.write(consoleScript.lstrip('\n').format(
                            version=tuple(sys.version_info),
                            python=sys.executable,
                            syspath=sys.path,
                            specdir=pathjoin(specdir, package)
                        ))
                except IOError as e:
                    messages.runerr('Se produjo el siguiente error al intentar instalar un enlace:', e)
                else:
                    chmod(pathjoin(bindir, package), 0o755)

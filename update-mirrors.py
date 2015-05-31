#!/usr/bin/python3
'''
Update git-svn mirrors of a git repository, and then push them to mirrored
GitHub repositories.

Assumes that the git-svn clone is already setup with GitHub as a remote branch,
SSH keys allow login to GitHub, and svn2git is installed.

Options are currently set with constants in the script.

To disable synchronization of a repo, move it out of GIT_SVN_DIR.
'''

import sys
import os
import shutil
import subprocess
from argparse import ArgumentParser
import logging
import logging.handlers


# Script-style constants, so we don't have to mess with options
PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
GIT_SVN_DIR = os.path.join(PROJECT_DIR, "svn-clones")
LOCKFILE_NAME = os.path.join(GIT_SVN_DIR, "update-in-progress")
LOG_DIR = os.path.join(PROJECT_DIR, "logs")
LOG_NAME = "update-mirrors.log"
LOG_LEVEL = logging.DEBUG
FILE_SIZE_LIMIT = "50M"


# Setup Logging
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)
log_format = "%(asctime)s [%(levelname)s] %(message)s"
log_date_format = "%m/%d/%Y %I:%M:%S %p"
log_formatter = logging.Formatter(fmt=log_format, datefmt=log_date_format)
log_stream_handler = logging.StreamHandler()
log_stream_handler.setLevel(logging.ERROR)
log_stream_handler.setFormatter(log_formatter)
logger.addHandler(log_stream_handler)
# Use the WatchedFileHandler so that logrotate can work without restarting the script
log_rotation_handler = logging.handlers.WatchedFileHandler(
                            filename=os.path.join(LOG_DIR, LOG_NAME))
log_rotation_handler.setLevel(LOG_LEVEL)
log_rotation_handler.setFormatter(log_formatter)
logger.addHandler(log_rotation_handler)
#logger.critical("HERE IS A MESSAGE") # Test message


def update_gitsvn(dirname):
    ''' Update Git-SVN from the source SVN.
        Do this by running svn2git in a pre-existing and pre-configured cloned
        repository.
    '''
    logger.info("Updating local mirror for %s" %(dirname))
    os.chdir(dirname)
    restart_sync = True
    try:
        while restart_sync == True:
            restart_sync = False
            with subprocess.Popen(('svn2git', '--rebase', '--metadata'),
                    stderr=subprocess.STDOUT,
                    stdout=subprocess.PIPE) as proc:
                logger.debug("Output from svn2git:")
                for l in proc.stdout.readlines():
                    logger.debug("\t%s"%(l))
                    if l.endswith(b'git-svn died of signal 13\n'):
                        restart_sync = True
                        logger.info("git-svn died of signal 13. Restarting.")
                proc.wait()
                if proc.returncode != 0 and restart_sync != True:
                    raise Exception("svn2git exited with an error: %s"
                                    %(proc.returncode))
    except Exception as e:
        logger.error("Something went wrong with svn2git rebase of %s: %s" %(dirname, e))


def strip_big_files(dirname):
    ''' Use BFG to remove large files from the repository. '''
    try:
        with subprocess.Popen(('bfg', '--strip-blobs-bigger-than', FILE_SIZE_LIMIT,
                               '--no-blob-protection', '.'),
                stderr=subprocess.STDOUT, stdout=subprocess.PIPE) as proc:
            logger.debug("Output from BFG:")
            for l in proc.stdout.readlines():
                logger.debug("\t%s"%(l))
            proc.wait()
            if proc.returncode != 0:
                raise Exception("BFG exited with an error: %s"
                                %(proc.returncode))
    except Exception as e:
        logger.error("Something went wrong while stripping large files in %s: %s" %(dirname, e))

    # Cleanup BFG
    try:
        try:
            shutil.rmtree(os.path.join(dirname, '..bfg-report'))
        except OSError as e:
            # ignore "OSError: [Errno 2] No such file or directory"
            if e.errno != 2: raise e
        with subprocess.Popen(('git', 'stash'),
                              stderr=subprocess.STDOUT, stdout=subprocess.PIPE) as proc:
            logger.debug("Output from Git stash while cleaning BFG:")
            for l in proc.stdout.readlines():
                logger.debug("\t%s"%(l))
            proc.wait()
            if proc.returncode != 0:
                raise Exception("Git stash exited with an error: %s"
                                %(proc.returncode))
        with subprocess.Popen(('git', 'stash', 'drop'),
                              stderr=subprocess.STDOUT, stdout=subprocess.PIPE) as proc:
            logger.debug("Output from Git stash while cleaning BFG:")
            for l in proc.stdout.readlines():
                logger.debug("\t%s"%(l))
            proc.wait()
            if proc.returncode != 0:
                if proc.returncode == 1: # No stash to drop
                    pass
                else:
                    raise Exception("Git stash exited with an error: %s"
                                %(proc.returncode))
    except Exception as e:
        logger.error("Something went wrong while stripping large files in %s: %s" %(dirname, e))


def push_to_github(dirname):
    ''' Push updates from local Git-SVN repo to GitHub
        Do this by running a git push with tags on a pre-existing and
        pre-configured repository.
    '''
    logger.info("Pushing updates to GitHub for %s" %(dirname))
    os.chdir(dirname)
    try:
        with subprocess.Popen(('git', 'push', '-u', '--tags', 'origin', 'master'),
                stderr=subprocess.STDOUT, stdout=subprocess.PIPE) as proc:
            logger.debug("Output from git push:")
            for l in proc.stdout.readlines():
                logger.debug("\t%s"%(l))
            proc.wait()
            if proc.returncode != 0:
                raise Exception("git push exited with an error: %s"
                                %(proc.returncode))
    except Exception as e:
        logger.error("Something went wrong with git push of %s: %s" %(dirname, e))


def get_lockfile():
    logger.debug("Checking if another update is running")
    if os.path.isfile(LOCKFILE_NAME):
        logger.warn("Update already running! Exiting.")
        sys.exit()
    else:
        try:
            f = open(LOCKFILE_NAME, 'w')
            f.close()
        except Exception as e:
            logger.error("Unable to claim the lock file.")
            raise(e)


def clean_lockfile():
    logger.debug("Cleaning lock file")
    try:
        os.remove(LOCKFILE_NAME)
    except Exception as e:
        logger.error("Unable to clean the lock file.")
        raise(e)


def main(arg_list):
    logger.info("STARTING UPDATE")
    get_lockfile()
    os.chdir(GIT_SVN_DIR)
    repos = [os.path.join(GIT_SVN_DIR, subdir) for subdir in os.listdir()
                    if os.path.isdir(subdir) and not subdir.startswith('.')]
    for repo in repos:
        update_gitsvn(repo)
        strip_big_files(repo)
        push_to_github(repo)
    clean_lockfile()
    logger.info("FINISHED UPDATE")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    sysargs = parser.parse_args()
    sys.exit(main(sysargs))


# vim:expandtab ts=4 sw=4 softtabstop=4 filetype=python

#!/bin/sh

ORIGINAL=/Library/AutoPkg/autopkglib/MunkiServerUploader.py

sudo mv -f $ORIGINAL $ORIGINAL.bak
sudo cp -f ./MunkiServerUploader.py /Library/AutoPkg/autopkglib/
sudo chmod 755 $ORIGINAL
exit 0

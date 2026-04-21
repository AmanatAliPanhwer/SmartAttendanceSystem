import PyInstaller.__main__
import os
import shutil

# Clean previous builds
if os.path.exists('build'):
    shutil.rmtree('build')
if os.path.exists('dist'):
    shutil.rmtree('dist')

PyInstaller.__main__.run([
    'app.py',
    '--onefile',
    '--name=SmartAttendance',
    '--icon=static/assets/logo.ico',
    '--add-data=static;static',
    '--add-data=templates;templates',
    '--add-data=models;models',
    '--hidden-import=sqlalchemy.ext.baked',
    '--hidden-import=pydantic.deprecated.decorator',
    '--hidden-import=pydantic.deprecated.class_validators',
    '--hidden-import=mediapipe',
    '--collect-all=mediapipe',
    '--collect-all=onnxruntime',
    '--clean',
])

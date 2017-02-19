from setuptools import setup
from setuptools.command.test import test as testcommand

import io
import os
import sys

import maxcul

here = os.path.abspath(os.path.dirname(__file__))


def read(*filenames, **kwargs):
    encoding = kwargs.get('encoding', 'utf-8')
    sep = kwargs.get('sep', '\n')
    buf = []
    for filename in filenames:
        with io.open(filename, encoding=encoding) as f:
            buf.append(f.read())
    return sep.join(buf)


long_description = read('README')


class PyTest(testcommand):
    def finalize_options(self):
        testcommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import pytest
        errcode = pytest.main(self.test_args)
        sys.exit(errcode)


setup(
    name='maxcul',
    version=maxcul.__version__,
    url='https://github.com/karlTGA/MaxCul-Python',
    license='BSD License',
    author='Markus Ullmann, Karl Wolffgang',
    tests_require=['pytest'],
    install_requires=['Flask>=0.12',
                      'Flask-SQLAlchemy>=2.1',
                      'blinker>=1.4',
                      'detach>=1.0',
                      'pyserial>=3.1.1',
                      'pytest>=3.0.5'
                      ],
    cmdclass={'test': PyTest},
    author_email='karlwolffgang@googlemail.com',
    description='Access with Python MAX! Devices over a CUL Stick',
    long_description=long_description,
    packages=['maxcul'],
    include_package_data=True,
    platforms='any',
    test_suite='maxcul.test.test_maxcul',
    classifiers=[
        'Programming Language :: Python',
        'Development Status :: 4 - Beta',
        'Natural Language :: English',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Home Automation'
    ],
    extras_require={
        'testing': ['pytest'],
    }
)

from setuptools import setup, find_packages

setup(
    name='scribble',
    version='0.1.0',
    description='Browser-based GUI for interactive plotting of CASA Measurement Set (MS) files',
    author='Your Name',
    packages=find_packages(),
    install_requires=[
        "bokeh",
        "datashader",
        "pandas",
        "python-casacore",
        "numpy"
    ],
    entry_points={
        'console_scripts': [
            'scribble = scribble.__main__:main',
        ],
    },
    python_requires=">=3.8"
)
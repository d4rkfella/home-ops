from setuptools import setup, find_packages

setup(
    name='kubecli',
    version='0.1.0',
    packages=find_packages(),
    install_requires=[],
    entry_points={
        'console_scripts': [
            'kubecli=kubecli.scripts.run_pods:main',
        ],
    },
)

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="mtc",
    version="1.1.2",
    author="Fastily",
    author_email="fastily@users.noreply.github.com",
    description="A simple CLI tool for moving enwp files to Commons",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/fastily/mtc2",
    project_urls={
        "Bug Tracker": "https://github.com/fastily/mtc2/issues",
    },
    include_package_data=True,
    packages=setuptools.find_packages(include=["mtc"]),
    install_requires=["fastilybot2", "python-dateutil", "rich", "requests"],
    entry_points={
        'console_scripts': [
            'mtc = mtc.__main__:_main'
        ]
    },
    classifiers=[
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9"
)

"""Setup package"""

from setuptools import setup, find_packages  # type: ignore

with open("README.md", "r") as fh:  # pylint: disable=unspecified-encoding
    LONG_DESCRIPTION = fh.read()

setup(
    name="pyrinnaitouch",
    packages=find_packages(exclude=["tests", "tests.*"]),
    version="0.15.0-alpha",
    license="mit",
    description="A python interface to the Rinnai Touch Wifi controller",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Funtastix",
    url="https://github.com/monkeyatcomputer/pyrinnaitouch",
    download_url="https://github.com/monkeyatcomputer/pyrinnaitouch/archive/refs/tags/v0.15.0-alpha.tar.gz",
    keywords=[
        "Rinnai Touch",
        "Brivis",
        "IoT",
    ],
    python_requires=">=3.9",
    tests_require=["pytest"],
    install_requires=[
        "typing_extensions>=4.0; python_version<'3.11'",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Home Automation",
        "Topic :: System :: Hardware",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
)

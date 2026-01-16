import os
import tarfile
import tempfile

from pygeoapi.process.base import ProcessorExecuteError
import requests


def download_and_extract_datastack(datastack_url, extracted_datastack_dir):
    """Download and extract a datastack tgz archive to a given local directory.

    Args:
        datastack_url (str): URL to download the datastack archive from
        extracted_datastack_dir (str): local directory path to extract to

    Returns:
        None
    """
    # Download the datastack from the given URL and
    response = requests.get(datastack_url)
    if response.status_code != 200:
        raise ProcessorExecuteError(
            "Failed to download datastack file. Request returned " +
            {response.status_code})

    with tempfile.TemporaryDirectory() as temp_dir:
        # save the datastack archive to a local temp file
        tgz_path = os.path.join(temp_dir, 'datastack.tgz')
        with open(tgz_path, 'wb') as tgz:
            tgz.write(response.content)

        # extract the TGZ archive to a local directory
        try:
            with tarfile.open(tgz_path, 'r:gz') as tgz:
                tgz.extractall(path=extracted_datastack_dir, filter='data')
        except Exception as err:
            raise ProcessorExecuteError(
                1, f'Failed to extract datastack archive:\n{str(err)}')

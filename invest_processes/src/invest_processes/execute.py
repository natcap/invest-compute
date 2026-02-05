import logging
from pathlib import Path
import textwrap

from invest_processes.utils import download_and_extract_datastack
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

LOGGER = logging.getLogger(__name__)

PROCESS_METADATA = {
    'version': '0.1.0',
    'id': 'invest-execute',
    'title': {
        'en': 'InVEST Execute'
    },
    'description': {
        'en': 'A process that executes an InVEST model.'
    },
    'jobControlOptions': ['async-execute'],
    'keywords': ['invest'],
    'inputs': {
        'datastack_path': {
            'title': 'Datastack path',
            'description': 'The path to the datastack JSON file to execute',
            'schema': {
                'type': 'string'
            },
            'minOccurs': 1,
            'maxOccurs': 1
        }
    },
    'outputs': {
        'workspace_url': {
            'title': 'Workspace URL',
            'description': 'URL to the workspace containing all model results',
            'schema': {
                'type': 'string',
                'contentMediaType': 'application/json'
            }
        }
    },
    'example': {
        'inputs': {
            'datastack_path': '/Users/emily/invest/data/Carbon/carbon_willamette.invs.json',
        }
    }
}


class ExecuteProcessor(BaseProcessor):
    """InVEST execute process"""

    def __init__(self, processor_def):
        """
        Initialize object

        Args:
            processor_def: provider definition

        Returns:
            invest_processes.processes.ExecuteProcessor
        """

        super().__init__(processor_def, PROCESS_METADATA)

    def create_slurm_script(self, datastack_url, workspace_dir):
        """Create a script to run with sbatch.

        Args:
            datastack_url: URL to the invest datastack (.tgz) to execute
            workspace_dir: path to the directory that the slurm job will run in

        Returns:
            string contents of the script
        """
        json_path, model_id = download_and_extract_datastack(
            datastack_url, Path(workspace_dir) / 'datastack')
        workspace_dir = Path(workspace_dir) / f'{model_id}_workspace'
        return textwrap.dedent(f"""\
            #!/bin/sh
            #SBATCH --time=10
            invest run --datastack {json_path} --workspace {workspace_dir} {model_id}
            """)

    def process_output(self, workspace_dir):
        """Return outputs given a workspace from completed slurm job.

        Args:
            workspace_dir (str): path to the slurm job working directory

        Returns:
            empty dict
        """
        pass

    def __repr__(self):
        return f'<InVESTExecuteProcessor> {self.name}'

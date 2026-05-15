import json
import os.path
import shutil
import subprocess
import tempfile
import time
import unittest

from invest_processes.utils import download_and_extract_datastack
from pygeoapi import flask_app

CARBON_DATASTACK_URL = 'https://raw.githubusercontent.com/natcap/invest-compute/refs/heads/main/tests/test_data/invest_carbon_datastack.tgz'
SQ_DATASTACK_URL = 'https://raw.githubusercontent.com/natcap/invest-compute/refs/heads/main/tests/test_data/invest_scenic_quality_datastack.tgz'
ERROR_DATASTACK_URL = 'https://raw.githubusercontent.com/natcap/invest-compute/refs/heads/main/tests/test_data/invest_carbon_error_datastack.tgz'


class PyGeoAPIServerTests(unittest.TestCase):

    def setUp(self):
        self.client = flask_app.APP.test_client()
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workspace_dir)

    def testExecuteProcessMetadata(self):
        response = self.client.get('/processes/invest-execute')
        self.assertEqual(response.status_code, 200)

    def testExecuteProcessExecutionSync(self):
        """Test execution of the 'execute' process in sync mode."""
        response = self.client.post('/processes/invest-execute/execution', json={
            'inputs': {
                'datastack_url': CARBON_DATASTACK_URL
            }
        })
        self.assertEqual(response.status_code, 200)
        execution_response = json.loads(response.get_data(as_text=True))
        # in sync mode with default response type ("raw"), the process
        # outputs should be returned directly in the json response
        self.assertEqual(set(execution_response.keys()), {'workspace_url'})

        job_id = response.headers['Location'].split('/')[-1]
        job_response = json.loads(self.client.get(f'/jobs/{job_id}').get_data(as_text=True))
        self.assertEqual(job_response['status'], 'successful')

        results_endpoint_response = json.loads(self.client.get(
            f'/jobs/{job_id}/results?f=json').get_data(as_text=True))
        # in sync mode, the same results should be returned from the initial
        # execution endpoint and from any subsequent calls to the results endpoint
        self.assertEqual(execution_response, results_endpoint_response)

        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive',
            f'{execution_response["workspace_url"]}/*', local_dest_path
        ], check=True)

        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'carbon_workspace',  # the invest model workspace directory
                'results.json'       # json results file used by pygeoapi
            }
        )

    def testExecuteProcessExecutionAsync(self):
        """Test execution of the 'execute' process in async mode."""
        response = self.client.post(
            '/processes/invest-execute/execution',
            json={'inputs': {'datastack_url': CARBON_DATASTACK_URL}},
            headers={'Prefer': 'respond-async'}
        )
        self.assertEqual(response.status_code, 201)
        execution_response = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(execution_response.keys()), {'status', 'type', 'jobID'})
        self.assertEqual(execution_response['status'], 'accepted')
        # according to the OGC standard this should always be 'process'
        self.assertEqual(execution_response['type'], 'process')
        self.assertIn(
            f'/jobs/{execution_response["jobID"]}',
            response.headers['Location'])

        # poll status until the job finishes
        # TODO: test with a longer running job
        while True:
            job_response = json.loads(self.client.get(
                f'/jobs/{execution_response["jobID"]}').get_data(as_text=True))
            self.assertNotIn(job_response['status'], {'failed', 'dismissed'})
            if job_response['status'] == 'successful':
                break
            time.sleep(5)

        results_response = json.loads(self.client.get(
            f'/jobs/{execution_response["jobID"]}/results?f=json').get_data(
            as_text=True))
        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive',
            f'{results_response["workspace_url"]}/*', local_dest_path
        ], check=True)
        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'carbon_workspace',  # the invest model workspace directory
                'results.json'       # json results file used by pygeoapi
            }
        )

    def testExecuteProcessExecutionSlowAsync(self):
        """Test execution in async mode with a longer-running job."""
        response = self.client.post(
            '/processes/invest-execute/execution',
            json={'inputs': {'datastack_url': SQ_DATASTACK_URL}},
            headers={'Prefer': 'respond-async'}
        )
        self.assertEqual(response.status_code, 201)
        execution_response = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(execution_response.keys()), {'status', 'type', 'jobID'})
        self.assertEqual(execution_response['status'], 'accepted')
        # according to the OGC standard this should always be 'process'
        self.assertEqual(execution_response['type'], 'process')
        self.assertIn(
            f'/jobs/{execution_response["jobID"]}',
            response.headers['Location'])

        # poll status until the job finishes
        # TODO: test with a longer running job
        while True:
            job_response = json.loads(self.client.get(
                f'/jobs/{execution_response["jobID"]}').get_data(as_text=True))
            if job_response['status'] in {'successful', 'failed', 'dismissed'}:
                break
            time.sleep(5)

        results_response = json.loads(self.client.get(
            f'/jobs/{execution_response["jobID"]}/results?f=json').get_data(
            as_text=True))

        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive',
            f'{results_response["workspace_url"]}/*', local_dest_path
        ], check=True)

        self.assertNotIn(job_response['status'], {'failed', 'dismissed'})
        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'scenic_quality_workspace',  # the invest model workspace directory
                'results.json'       # json results file used by pygeoapi
            }
        )

    def testExecuteProcessErrorSync(self):
        """Test executing a datastack that should cause a model error."""
        response = self.client.post(
            '/processes/invest-execute/execution',
            json={'inputs': {'datastack_url': ERROR_DATASTACK_URL}}
        )
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data.keys()), {'workspace_url'})

        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive',
            f'{data["workspace_url"]}/*', local_dest_path
        ], check=True)

        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'carbon_workspace',  # the invest model workspace directory
                'results.json'       # json results file used by pygeoapi
            }
        )

        # expect model error to be captured in stderr.log
        with open(os.path.join(local_dest_path, 'stderr.log')) as err_log:
            self.assertIn(
                'RuntimeError: does_not_exist.tif: No such file or directory',
                err_log.read())

    def testValidateProcessMetadata(self):
        response = self.client.get('/processes/invest-validate')
        self.assertEqual(response.status_code, 200)

    def testValidateProcessExecutionSync(self):
        """Validation of a datastack should return validation messages"""
        response = self.client.post('/processes/invest-validate/execution', json={
            'inputs': {
                'datastack_url': CARBON_DATASTACK_URL
            }
        })
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.get_data(as_text=True))
        self.assertEqual(set(data.keys()),
                         {'workspace_url', 'validation_results'})
        self.assertEqual(
            data['validation_results'],
            [{
                'input_ids': ['workspace_dir'],
                'error_message': 'Key is missing from the args dict'
            }]
        )

        local_dest_path = os.path.join(self.workspace_dir, 'results')
        os.mkdir(local_dest_path)
        subprocess.run([
            'gcloud', 'storage', 'cp', '--recursive',
            f'{data["workspace_url"]}/*', local_dest_path
        ], check=True)
        self.assertEqual(
            set(os.listdir(local_dest_path)),
            {
                'datastack',         # extracted datastack directory
                'stdout.log',        # stdout from the slurm job
                'stderr.log',        # stderr from the slurm job
                'script.slurm',      # the slurm script sent to sbatch
                'results.json'       # json results file used by pygeoapi
            }
        )

    def testGetSyncJobResults(self):
        response = self.client.post(
            '/processes/invest-execute/execution',
            json={'inputs': {'datastack_url': ERROR_DATASTACK_URL}},
            query_string={'f': 'json'}
        )
        # self.assertEqual(response.status_code, 200)

        job_id = response.headers['Location'].split('/')[-1]
        response = self.client.get(f'/jobs/{job_id}/results?f=json').get_data(as_text=True)
        print('response:', response)
        job_result = json.loads(response)
        print('result:', job_result)

    def testGetAsyncJobResults(self):
        response = self.client.post(
            '/processes/invest-execute/execution',
            json={'inputs': {'datastack_url': ERROR_DATASTACK_URL}},
            headers={'Prefer': 'respond-async'},
            query_string={'f': 'json'}
        )
        self.assertEqual(response.status_code, 200)

        job_id = response.headers['Location'].split('/')[-1]
        response = self.client.get(f'/jobs/{job_id}/results?f=json').get_data(as_text=True)
        print('response:', response)
        job_result = json.loads(response)
        print('result:', job_result)



class UtilsTests(unittest.TestCase):

    def setUp(self):
        self.workspace_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.workspace_dir)

    def testDownloadAndExtractDatastack(self):
        """Test utility function for downloading and extracting a datastack."""
        json_path, model_id = download_and_extract_datastack(
            CARBON_DATASTACK_URL, self.workspace_dir)
        self.assertEqual(
            set(os.listdir(self.workspace_dir)),
            {'data', 'log.txt', 'parameters.invest.json'}
        )
        self.assertEqual(json_path, os.path.join(
            self.workspace_dir, 'parameters.invest.json'))
        self.assertEqual(model_id, 'carbon')

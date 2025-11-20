## hpc-slurm.yml
Cluster blueprint file for use with Google Cluster Toolkit.
Adapted from the example:
https://github.com/GoogleCloudPlatform/cluster-toolkit/blob/main/examples/hpc-slurm.yaml

Install Google Cluster Toolkit following the instructions:
https://docs.cloud.google.com/cluster-toolkit/docs/setup/configure-environment

To build the deployment folder from the blueprint:
``
~/cluster-toolkit/gcluster create hpc-slurm.yml -l ERROR --vars project_id=natcap-servers
``
This creates the `hpc-slurm` directory, which contains the terraform files.

To interact directly with terraform:
``
cd hpc-slurm
terraform init
terraform plan  # show changes that would be made by apply
terraform apply  # deploy infrastructure
``

To deploy:
``
./gcluster deploy hpc-slurm
``

If you're authenticated with `gcloud`, you should be able to SSH into the login node:
``
gcloud compute ssh hpcslurm-slurm-login-001 --tunnel-through-iap
``

## Ansible

Install Ansible:
``
pip install ansible
``

### ansible.cfg
Ansible configuration file. Using this to enable the the `google.cloud.gcp_compute` plugin, which dynamically inventories GCP resources.

### gcp.yml
Configures the `google.cloud.gcp_compute` plugin to dynamically find the GCP VM that we want to apply the playbook to (in this case the slurm login node).

Note: this file MUST be called `gcp.yml` (or `gcp_compute.yml`) EVEN when you directly point to it with the `-i` flag. This is an undocumented requirement that I only figured out by looking at the plugin source code.






## Deploy and configure an invest compute cluster

This repo uses Terraform (via Google Cluster Toolkit) and Ansible to define the infrastructure and configuration needed to run an invest compute cluster. Our goal is for users to be able to easily deploy an equivalent invest compute cluster in their own GCP project. This way, users may make use of the invest compute services while paying for the infrastructure from their own funding.

### Deployment workflow
Install Google Cluster Toolkit following the instructions:
https://docs.cloud.google.com/cluster-toolkit/docs/setup/configure-environment
The following steps assume that the resulting executable exists at `~/cluster-toolkit/gcluster`. All the commands below are run on your development machine, it is not necessary to directly run anything on the cluster instances.

From this directory, run:
```
~/cluster-toolkit/gcluster create hpc-slurm.yml --vars project_id=natcap-servers
```
This uses the `hpc-slurm.yml` blueprint to create the `hpc-slurm` deployment folder, which contains the terraform files.

To deploy:
```
~/cluster-toolkit/gcluster deploy hpc-slurm
```
This will create the infrastructure defined in `hpc-slurm` in your GCP project. At this point, all the necessary GCP resources are in place, but we still need to install software and launch the server.

~~Be careful with the `terraform.tfstate` file! It's created in the `hpc-slurm` directory and it tracks what Terraform knows about your infrastructure. If you delete it, it's difficult to recover that information.~~

Install Ansible:
```
pip install ansible
ansible-galaxy install mambaorg.micromamba
```

If you're authenticated with `gcloud`, you should be able to SSH into the login node:
```
gcloud compute ssh hpcslurm-slurm-login-001 --tunnel-through-iap
```
In order to run Ansible, you'll need to configure regular SSH to the instance (without `gcloud` or IAP tunneling). `gcloud compute config-ssh` is some help with this, but for me there was some trial and error. Make sure that you can connect to the login node like so:
```
ssh <username>@<external ip address>
```
Your username on the instance can be found by separately SSHing into it (easily done with the SSH button in the GCP console). The external IP address can also be found in the GCP console.

So that we do not have to list out the IP addresses of each target node, we are using the `google.cloud.gcp_compute` plugin to dynamically inventory our instances. The dynamic inventory is configured in `gcp.yml`.

Run the playbook:
```
ansible-playbook -vvv -i gcp.yml login_node_playbook.yml
```
At this point, the nodes should be configured and the pygeoapi server should be running on the login node.


Note: you can interact directly with Terraform as well as indirectly through Cluster Toolkit:
```
cd hpc-slurm
terraform init
terraform plan  # show changes that would be made by apply
terraform apply  # deploy infrastructure
```


## hpc-slurm.yml
Cluster blueprint file for use with Google Cluster Toolkit.
Adapted from the example:
https://github.com/GoogleCloudPlatform/cluster-toolkit/blob/main/examples/hpc-slurm.yaml


## ansible.cfg
Ansible configuration file. Using this to enable the the `google.cloud.gcp_compute` plugin, which dynamically inventories GCP resources.

## gcp.yml
Configures the `google.cloud.gcp_compute` plugin to dynamically find the GCP VM that we want to apply the playbook to (in this case the slurm login node).

Note: this file MUST be called `gcp.yml` (or `gcp_compute.yml`) EVEN when you directly point to it with the `-i` flag. This is an undocumented requirement that I only figured out by looking at the plugin source code.






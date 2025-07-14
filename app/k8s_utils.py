from kubernetes import client, config

def create_user_pod_and_service(pod_name, svc_name, env_vars=None):
    config.load_incluster_config()
    api = client.CoreV1Api()

    if env_vars is None:
        env_vars = []

    container = client.V1Container(
        name="code-runner",
        image="container7.azurecr.io/code-runner:latest",
        ports=[client.V1ContainerPort(container_port=5000)],
        env=[client.V1EnvVar(name=var["name"], value=var["value"]) for var in env_vars]
    )

    pod_spec = client.V1PodSpec(
        containers=[container],
        image_pull_secrets=[client.V1LocalObjectReference(name="acr-pull-secret")],
        service_account_name="pod-manager"
    )
    pod_metadata = client.V1ObjectMeta(name=pod_name, labels={"app": pod_name})
    pod = client.V1Pod(metadata=pod_metadata, spec=pod_spec)
    api.create_namespaced_pod(namespace="default", body=pod)

    service_spec = client.V1ServiceSpec(
        selector={"app": pod_name},
        ports=[client.V1ServicePort(port=5000, target_port=5000)],
        type="ClusterIP"
    )
    service_metadata = client.V1ObjectMeta(name=svc_name)
    service = client.V1Service(metadata=service_metadata, spec=service_spec)
    api.create_namespaced_service(namespace="default", body=service)

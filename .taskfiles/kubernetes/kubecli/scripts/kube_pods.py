# .taskfiles/kubernetes/kubecli/scripts/run_pods.py
from kubecli.resources.kube_pods import PodManager

if __name__ == "__main__":
    manager = PodManager()
    manager.run()

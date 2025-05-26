from kubecli.resources.kube_pods import PodManager

def main():
    manager = PodManager()
    manager.run()

if __name__ == "__main__":
    main()

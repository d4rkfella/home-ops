---
apiVersion: v1alpha1
kind: KubeletConfig
defaultRuntimeSeccompProfileEnabled: true
config:
  imageGCHighThresholdPercent: 85
  imageGCLowThresholdPercent: 65
  maxParallelImagePulls: 10
  maxPods: 400
  serializeImagePulls: false
  serverTLSBootstrap: true
  shutdownGracePeriod: 5m
  shutdownGracePeriodCriticalPods: 2m
  cpuManagerPolicy: static
  cpuManagerPolicyOptions:
    full-pcpus-only: "true"
---
apiVersion: v1alpha1
kind: KubeNodeConfig
nodeIP:
  validSubnets:
    - 192.168.91.0/24

---
apiVersion: v1alpha1
kind: KubeNetworkConfig
dnsDomain: cluster.local
podSubnets:
    - 172.16.0.0/16
serviceSubnets:
    - 172.17.0.0/16
---
apiVersion: v1alpha1
kind: KubeFlannelCNIConfig
$patch: delete

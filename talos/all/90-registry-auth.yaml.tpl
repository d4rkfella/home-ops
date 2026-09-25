---
apiVersion: v1alpha1
kind: RegistryAuthConfig
name: ghcr.io
username: {{ .Data.GHCR_USERNAME }}
password: {{ .Data.GHCR_PASSWORD }}

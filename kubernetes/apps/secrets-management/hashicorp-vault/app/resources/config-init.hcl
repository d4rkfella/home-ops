"auto_auth" = {
      "method" = {
        "config" = {
          "role" = "vault"
        }
        "type" = "kubernetes"
      }
      "sink" = {
        "config" = {
          "path" = "/home/appuser/.aws/token"
          "mode" = 0644
        }
        "type" = "file"
      }
    }
    "exit_after_auth" = true
    "template" = {
      "contents" =
        "{{- with secret \"secrets/vault\" -}}\n[default]\naws_access_key_id = {{ .Data.data.AWS_ACCESS_KEY_ID }}\naws_secret_access_key = {{ .Data.data.AWS_SECRET_ACCESS_KEY }}\n{{- end -}}"
      "destination" = "/home/appuser/.aws/credentials"
    }

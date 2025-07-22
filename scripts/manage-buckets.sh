#!/usr/bin/env bash
set -euo pipefail
IFS=$'
\t'

AWS_CONFIG_FILE=${AWS_CONFIG_FILE:-"$HOME/.aws/config"}

# Get the base endpoint_url for a given profile from ~/.aws/config
get_base_endpoint_for_profile() {
  local profile="$1"
  local services_name

  if [[ ! -f "$AWS_CONFIG_FILE" ]]; then
    echo "" # No config file, no endpoint
    return
  fi

  # Get the name of the services block for the selected profile
  services_name=$(awk -v profile="$profile" '
    $0 == "[profile " profile "]" {found=1; next}
    /^\[/ && found {exit} # Stop if we hit another section
    found && /^services *=/ {
      gsub(/services *= */, "", $0);
      print $0; exit
    }
  ' "$AWS_CONFIG_FILE" || echo "")

  if [[ -z "$services_name" ]]; then
    echo "" # No services configured for this profile
    return
  fi

  # Now get the endpoint_url from the corresponding [services ...] block
  awk -v services_name="$services_name" '
    $0 == "[services " services_name "]" {found=1; next}
    /^\[/ && found {exit} # Stop if we hit another section
    found && /^[[:space:]]*endpoint_url[[:space:]]*=[[:space:]]*/ {
      gsub(/.*=[[:space:]]*/, "", $0);
      print $0; exit
    }
  ' "$AWS_CONFIG_FILE" || echo ""
}

# Determines the correct endpoint for a bucket by checking its location.
# Falls back to the base endpoint if location cannot be determined.
# Generates a list of all possible R2 endpoints to check, given a base endpoint.
get_all_possible_endpoints() {
    local base_endpoint=$1
    local endpoints_to_check=()

    if [[ -z "$base_endpoint" ]]; then
        return
    fi

    # Normalize the base endpoint by removing any known jurisdiction to avoid duplicates.
    local base_endpoint_normalized
    base_endpoint_normalized=$(echo "$base_endpoint" | sed -E 's/\.(eu|apac|ensa|wesa)\.r2\.cloudflarestorage\.com/\.r2\.cloudflarestorage\.com/')

    # Always include the user's original configured endpoint first.
    endpoints_to_check+=("$base_endpoint")

    # Then add the normalized base endpoint if it's different.
    if [[ "$base_endpoint_normalized" != "$base_endpoint" ]]; then
        endpoints_to_check+=("$base_endpoint_normalized")
    fi

    # Finally, add all other jurisdictional endpoints based on the normalized URL.
    local jurisdictions=("eu" "apac" "ensa" "wesa")
    for jurisdiction in "${jurisdictions[@]}"; do
        local regional_endpoint
        regional_endpoint=$(echo "$base_endpoint_normalized" | sed "s#\(\.r2\.cloudflarestorage\.com\)#.$jurisdiction\1#")
        if ! [[ " ${endpoints_to_check[*]} " =~ " ${regional_endpoint} " ]]; then
            endpoints_to_check+=("$regional_endpoint")
        fi
    done

    # Print each endpoint on a new line.
    printf '%s\n' "${endpoints_to_check[@]}"
}


# Run aws s3/s3api command with the correct auto-detected endpoint
aws_s3() {
  local profile="$1"
  local endpoint="$2"
  local command=("${@:3}") # Capture the actual command

  if [[ -n "$endpoint" ]]; then
    aws --endpoint-url "$endpoint" --profile "$profile" "${command[@]}"
  else
    aws --profile "$profile" "${command[@]}"
  fi
}

# Prompt user to press enter to continue
press_enter_to_continue() {
  read -rp "Press Enter to continue..."
}

# Select AWS profile using aws CLI, fallback to default if none
select_aws_profile() {
  local profiles profile
  profiles=($(aws configure list-profiles))
  if [[ ${#profiles[@]} -eq 0 ]]; then
    echo "No AWS profiles found. Exiting." >&2
    exit 1
  fi

  local exit_option="<-- Exit"
  local fzf_input=("${profiles[@]}" "$exit_option")

  profile=$(printf '%s\n' "${fzf_input[@]}" | fzf --prompt="Select AWS profile> ")

  if [[ -z "$profile" || "$profile" == "$exit_option" ]]; then
    echo "" # Return empty to signal exit
  else
    echo "$profile"
  fi
}

# List buckets for a profile, creating a map of endpoint -> bucket.
list_buckets() {
  local profile=$1
  local base_endpoint
  base_endpoint=$(get_base_endpoint_for_profile "$profile")

  if [[ -z "$base_endpoint" ]]; then
      # No R2/S3-like endpoint configured, try standard aws call.
      # We prepend "default|" as the placeholder endpoint.
      aws --profile "$profile" s3api list-buckets --query "Buckets[].Name" --output text 2>/dev/null | tr '\t' '\n' | sed 's/^/default|/'
      return
  fi

  # We'll query all known jurisdictional endpoints to build a complete list.
  mapfile -t endpoints_to_check < <(get_all_possible_endpoints "$base_endpoint")

  # Run all endpoint checks in parallel and combine their output.
  # This is much faster than checking them sequentially.
  local all_buckets_unsorted
  all_buckets_unsorted=$( (
    for endpoint in "${endpoints_to_check[@]}"; do
      # For each endpoint, list its buckets and prepend the endpoint to each line.
      (aws --endpoint-url "$endpoint" --profile "$profile" s3api list-buckets --query "Buckets[].Name" --output text 2>/dev/null | tr '\t' '\n' | sed "s#^#$endpoint|#" || true) &
    done
    wait
  ) )

  # Unique buckets and print
  if [[ -n "$all_buckets_unsorted" ]]; then
    echo "$all_buckets_unsorted" | sort -u
  else
    # To ensure the function doesn't return old values if all calls fail.
    echo ""
  fi
}

# List objects and common prefixes (folders) in a bucket/prefix
list_objects() {
  local profile=$1 bucket=$2 prefix=${3:-""} endpoint=${4}
  local query="[CommonPrefixes[].Prefix, Contents[].Key][]"
  local args=(--delimiter "/")

  if [[ -n "$prefix" ]]; then
    args+=(--prefix "$prefix")
  fi
  # Combine "folders" (CommonPrefixes) and "files" (Contents), then filter out the prefix itself
  # which can be returned as a key if it's also an object.
  aws_s3 "$profile" "$endpoint" s3api list-objects-v2 --bucket "$bucket" "${args[@]}" --query "$query" --output text | tr '\t' '\n' | grep -Fxv "$prefix" || true
}

# Delete a single object
delete_object() {
  local profile=$1 bucket=$2 object=$3 endpoint=$4
  aws_s3 "$profile" "$endpoint" s3api delete-object --bucket "$bucket" --key "$object"
  echo "Deleted object '$object' from bucket '$bucket'."
}

# Delete all objects under a prefix
delete_prefix() {
  local profile=$1 bucket=$2 prefix=$3 endpoint=$4
  echo "Are you sure you want to DELETE ALL objects under prefix '$prefix'? This will recursively delete everything inside."
  select yn in "Yes (delete)" "Dry-run (show what would be deleted)" "No (cancel)"; do
    case $yn in
      "Yes (delete)")
        echo "Deleting all objects recursively under '$prefix'..."
        aws_s3 "$profile" "$endpoint" s3 rm "s3://$bucket/$prefix" --recursive
        echo "All objects under '$prefix' deleted."
        press_enter_to_continue
        break
        ;;
      "Dry-run (show what would be deleted)")
        echo "Dry-run: Showing objects that would be deleted under '$prefix':"
        aws_s3 "$profile" "$endpoint" s3 rm "s3://$bucket/$prefix" --recursive --dryrun
        press_enter_to_continue
        break
        ;;
      "No (cancel)")
        echo "Cancelled deletion."
        break
        ;;
    esac
  done
}

# Delete entire bucket (all objects + bucket)
delete_bucket() {
  local profile=$1 bucket=$2 endpoint=$3

  echo "Are you sure you want to DELETE ENTIRE BUCKET '$bucket'? This will delete ALL objects!"
  select yn in "Yes (delete)" "Dry-run (show what would be deleted)" "No (cancel)"; do
    case $yn in
      "Yes (delete)")
        echo "Deleting all objects recursively..."
        aws_s3 "$profile" "$endpoint" s3 rm "s3://$bucket" --recursive
        echo "Deleting the bucket..."
        aws_s3 "$profile" "$endpoint" s3api delete-bucket --bucket "$bucket"
        echo "Bucket '$bucket' deleted."
        press_enter_to_continue
        break
        ;;
      "Dry-run (show what would be deleted)")
        echo "Dry-run: Showing objects that would be deleted:"
        aws_s3 "$profile" "$endpoint" s3 rm "s3://$bucket" --recursive --dryrun
        press_enter_to_continue
        break
        ;;
      "No (cancel)")
        echo "Cancelled deletion."
        break
        ;;
    esac
  done
}

# Browse objects in bucket with fzf, with prefix navigation
browse_objects() {
  local profile=$1 bucket=$2 endpoint=$3
  local prefix=""

  while true; do
    local fzf_input=()
    # At the root, "../" means back to bucket list. Otherwise, it means up one level.
    fzf_input+=("../")

    mapfile -t items < <(list_objects "$profile" "$bucket" "$prefix" "$endpoint")
    if [[ ${#items[@]} -gt 0 ]]; then
        fzf_input+=("${items[@]}")
    fi

    if [[ ${#fzf_input[@]} -eq 0 ]]; then
        echo "Directory is empty."
        press_enter_to_continue
        if [[ -n "$prefix" ]]; then # If not at root, go up
            prefix=$(dirname "${prefix%/}")/
            [[ "$prefix" == "./" || "$prefix" == "/" ]] && prefix=""
            continue
        else # at root and empty, so exit
            break
        fi
    fi

    local prompt="Bucket '$bucket/${prefix}' (Enter=navigate, Ctrl+D/T=delete): "
    local output key selected_item
    output=$(printf '%s\n' "${fzf_input[@]}" | \
      fzf --prompt="$prompt" --expect=ctrl-d,ctrl-t)
    fzf_exit_code=$?

    # Exit on Esc or Ctrl-C
    if [[ $fzf_exit_code -eq 130 ]]; then
        break
    fi

    [[ -z "$output" ]] && continue # Nothing selected

    mapfile -t lines <<< "$output"
    key="${lines[0]}"
    selected_item="${lines[1]}"

    if [[ -z "$key" ]]; then # Enter was pressed
        if [[ "$selected_item" == "../" ]]; then
            if [[ -z "$prefix" ]]; then
                # At root, so ".." means go back to bucket list
                break
            else
                # Not at root, so ".." means go up one level
                prefix=$(dirname "${prefix%/}")/
                [[ "$prefix" == "./" || "$prefix" == "/" ]] && prefix=""
            fi
        elif [[ "${selected_item: -1}" == "/" ]]; then # Directory
            prefix=$selected_item
        else # File
            echo "Selected object '$selected_item' (no action on Enter, use Ctrl-D/T to delete)."
            press_enter_to_continue
        fi
    elif [[ "$key" == "ctrl-d" || "$key" == "ctrl-t" ]]; then
        if [[ "$selected_item" == "../" ]]; then
            continue # Can't delete ..
        fi
        if [[ "${selected_item: -1}" == "/" ]]; then # Directory/Prefix
            delete_prefix "$profile" "$bucket" "$selected_item" "$endpoint"
        else # File
            echo "Confirm delete of object '$selected_item'?"
            select yn in "Yes (delete)" "Dry-run (show what would be deleted)" "No (cancel)"; do
              case $yn in
                "Yes (delete)")
                  delete_object "$profile" "$bucket" "$selected_item" "$endpoint"
                  press_enter_to_continue
                  break
                  ;;
                "Dry-run (show what would be deleted)")
                  echo "Dry-run: This would delete object '$selected_item' in bucket '$bucket':"
                  aws_s3 "$profile" "$endpoint" s3 rm "s3://$bucket/$selected_item" --dryrun
                  press_enter_to_continue
                  break
                  ;;
                "No (cancel)")
                  echo "Cancelled."
                  break
                  ;;
              esac
            done
        fi
    fi
  done
  echo "Back to bucket list."
}

main() {
  while true; do
    local profile
    profile=$(select_aws_profile)

    if [[ -z "$profile" ]]; then
      echo "Exiting."
      break # Exit main loop
    fi

    echo "Using AWS profile: $profile"

    # Fetch the bucket list once per profile and cache it.
    mapfile -t bucket_map < <(list_buckets "$profile")

    while true; do # Bucket selection loop
      if [[ ${#bucket_map[@]} -eq 0 ]]; then
        echo "No buckets found for profile '$profile'."
        press_enter_to_continue
        break # Go back to profile selection
      fi

      local back_option="<-- Back to profile selection"
      # We only show the bucket names to fzf.
      local bucket_names
      bucket_names=$(printf '%s\n' "${bucket_map[@]}" | cut -d'|' -f2-)
      local fzf_input=("$back_option" "$bucket_names")

      local output key selected_item bucket_name endpoint
      output=$(printf '%s\n' "${fzf_input[@]}" | \
        fzf --prompt="Bucket> " --expect=ctrl-d,ctrl-t)
      local fzf_exit_code=$?

      if [[ $fzf_exit_code -eq 130 ]]; then
        # ESC/Ctrl-C pressed, go back to profile selection
        break
      fi

      [[ -z "$output" ]] && continue # Should not happen

      mapfile -t lines <<< "$output"
      key="${lines[0]}"
      selected_item="${lines[1]}"

      if [[ "$selected_item" == "$back_option" ]]; then
        break # Go back to profile selection
      fi

      # Find the full map entry for the selected bucket name to get its endpoint.
      local map_entry
      map_entry=$(printf '%s\n' "${bucket_map[@]}" | grep -F -- "|${selected_item}")
      endpoint=$(echo "$map_entry" | cut -d'|' -f1)
      bucket_name=$(echo "$map_entry" | cut -d'|' -f2-)

      if [[ "$endpoint" == "default" ]]; then
          endpoint="" # Use aws-cli default
      fi

      if [[ -z "$key" ]]; then
        # Enter was pressed, so the key is empty.
        browse_objects "$profile" "$bucket_name" "$endpoint"
      elif [[ "$key" == "ctrl-d" || "$key" == "ctrl-t" ]]; then
        # One of the keys from --expect was pressed.
        delete_bucket "$profile" "$bucket_name" "$endpoint"
        # after deletion, reload bucket list and continue the loop.
        mapfile -t bucket_map < <(list_buckets "$profile")
      fi
    done
  done
}

main "$@"

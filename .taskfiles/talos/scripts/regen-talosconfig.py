#!/usr/bin/env python3
"""
Creates new talosconfig key pair using the root Talos API CA from the control plane machine configuration.
"""

import os
import sys
import subprocess
import base64
import yaml
import argparse
import tempfile
import shutil


def run_command(cmd, check=True, capture_output=True, cwd=None):
    """Run a shell command and return the result"""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=capture_output, text=True, cwd=cwd)
    if result.returncode != 0:
        print(f"❌ Command failed with exit code {result.returncode}", file=sys.stderr)
        if result.stderr:
            print(f"Error output: {result.stderr}", file=sys.stderr)
        if result.stdout:
            print(f"Standard output: {result.stdout}", file=sys.stderr)
        if check:
            sys.exit(1)
    return result


def extract_ca_from_controlplane(controlplane_file, work_dir, use_sops=True):
    """Extract CA certificate and key from control plane config"""
    print(f"\n📄 Extracting CA from {controlplane_file}...")

    if not os.path.exists(controlplane_file):
        print(f"Error: Control plane file not found: {controlplane_file}", file=sys.stderr)
        sys.exit(1)

    ca_crt_path = os.path.join(work_dir, "ca.crt")
    ca_key_path = os.path.join(work_dir, "ca.key")

    if use_sops:
        print("🔓 Decrypting with SOPS...")
        decrypt_result = run_command(['sops', '-d', controlplane_file])
        decrypted_content = decrypt_result.stdout
    else:
        with open(controlplane_file, 'r') as f:
            decrypted_content = f.read()

    try:
        config = None
        for doc in yaml.safe_load_all(decrypted_content):
            if doc and 'machine' in doc and 'ca' in doc.get('machine', {}):
                config = doc
                break

        if not config:
            print(f"Error: Could not find machine.ca in any YAML document", file=sys.stderr)
            sys.exit(1)

    except yaml.YAMLError as e:
        print(f"Error: Failed to parse YAML: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        ca_crt_b64 = config['machine']['ca']['crt']
    except (KeyError, TypeError) as e:
        print(f"Error: Could not find machine.ca.crt in control plane config", file=sys.stderr)
        sys.exit(1)

    if not ca_crt_b64:
        print("Error: machine.ca.crt is empty", file=sys.stderr)
        sys.exit(1)

    ca_crt = base64.b64decode(ca_crt_b64)
    with open(ca_crt_path, 'wb') as f:
        f.write(ca_crt)
    print(f"✅ Extracted ca.crt")

    try:
        ca_key_b64 = config['machine']['ca']['key']
    except (KeyError, TypeError) as e:
        print(f"Error: Could not find machine.ca.key in control plane config", file=sys.stderr)
        sys.exit(1)

    if not ca_key_b64:
        print("Error: machine.ca.key is empty", file=sys.stderr)
        sys.exit(1)

    ca_key = base64.b64decode(ca_key_b64)
    with open(ca_key_path, 'wb') as f:
        f.write(ca_key)
    print(f"✅ Extracted ca.key")


def generate_new_certificate(work_dir):
    """Generate new admin certificate using talosctl"""
    print("\n🔑 Generating new admin certificate...")

    try:
        run_command(['talosctl', 'gen', 'key', '--name', 'admin'], cwd=work_dir)
        print("✅ Generated admin.key")

        run_command(['talosctl', 'gen', 'csr', '--key', 'admin.key', '--ip', '127.0.0.1'], cwd=work_dir)
        print("✅ Generated admin.csr")

        run_command([
            'talosctl', 'gen', 'crt',
            '--ca', 'ca',
            '--csr', 'admin.csr',
            '--name', 'admin',
            '--hours', '8760' # 1 year
        ], cwd=work_dir)
        print("✅ Generated admin.crt")

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error generating certificate", file=sys.stderr)
        raise

    return (
        os.path.join(work_dir, "ca.crt"),
        os.path.join(work_dir, "admin.crt"),
        os.path.join(work_dir, "admin.key")
    )


def read_and_encode(file_path):
    """Read a file and return its base64-encoded content"""
    with open(file_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def update_talosconfig(talosconfig_path, ca_crt_path, admin_crt_path, admin_key_path, context_name='default', endpoints=None, nodes=None):
    """Create a talosconfig file with new credentials"""
    print(f"\n📝 Creating {talosconfig_path}...")

    config = {
        'context': context_name,
        'contexts': {
            context_name: {
                'endpoints': endpoints if endpoints else [],
                'nodes': nodes if nodes else [],
                'ca': read_and_encode(ca_crt_path),
                'crt': read_and_encode(admin_crt_path),
                'key': read_and_encode(admin_key_path)
            }
        }
    }

    os.makedirs(os.path.dirname(os.path.abspath(talosconfig_path)), exist_ok=True)
    with open(talosconfig_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"✅ Created {talosconfig_path}")
    print(f"\n📋 Context: {context_name}")


def main():
    parser = argparse.ArgumentParser(
        description='Creates new talosconfig key pair using the root Talos API CA from the control plane machine configuration.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog = (
            "examples:\n"
            "  # Generate talosconfig in current directory\n"
            "  %(prog)s controlplane.yaml\n\n"
            "  # Specify output location\n"
            "  %(prog)s controlplane.yaml -o ~/.talos/config\n\n"
            "  # Add endpoints and custom context name\n"
            "  %(prog)s controlplane.yaml -o talosconfig -e 192.168.1.10 192.168.1.11 --context prod\n\n"
            "  # Skip SOPS decryption\n"
            "  %(prog)s controlplane.yaml --no-sops\n\n"
            "  # Keep temp files for debugging\n"
            "  %(prog)s controlplane.yaml --keep-temp\n"
        )
    )
    parser.add_argument(
        'controlplane',
        help='Path to control plane machine configuration file (e.g., controlplane.yaml)'
    )
    parser.add_argument(
        '--output', '-o',
        default='talosconfig',
        help='Output path for new talosconfig (default: talosconfig in current directory)'
    )
    parser.add_argument(
        '--endpoints', '-e',
        nargs='+',
        help='Control plane endpoints'
    )
    parser.add_argument(
        '--nodes', '-n',
        nargs='+',
        help='Node IPs or hostnames'
    )
    parser.add_argument(
        '--context',
        default='default',
        help='Context name for the talosconfig (default: default)'
    )
    parser.add_argument(
        '--keep-temp',
        action='store_true',
        help='Keep temporary files (for debugging)'
    )
    parser.add_argument(
        '--no-sops',
        action='store_true',
        help='Do not decrypt with SOPS (file is already decrypted)'
    )

    args = parser.parse_args()

    output_path = args.output

    work_dir = tempfile.mkdtemp(prefix='talos-regen-')
    print(f"🔧 Working directory: {work_dir}")

    try:
        extract_ca_from_controlplane(
            args.controlplane,
            work_dir,
            use_sops=not args.no_sops
        )

        ca_crt_path, admin_crt_path, admin_key_path = generate_new_certificate(work_dir)

        update_talosconfig(output_path, ca_crt_path, admin_crt_path, admin_key_path,
                          context_name=args.context, endpoints=args.endpoints, nodes=args.nodes)

        print(f"\n✨ Success! Talos config regenerated: {output_path}")

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        if not args.keep_temp:
            shutil.rmtree(work_dir)
            print(f"\n🧹 Cleaned up temporary files")
        else:
            print(f"\n📁 Temporary files kept in: {work_dir}")


if __name__ == '__main__':
    main()

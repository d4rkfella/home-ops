#!/usr/bin/env python3
import click
from kubecli.resources.kube_pods import PodManager
from kubecli.resources.kube_services import ServiceManager

@click.group()
def cli():
    """Kubernetes CLI tool for managing resources interactively."""
    pass

@cli.command()
def pods():
    """Manage Kubernetes pods."""
    manager = PodManager()
    manager.navigate()

@cli.command()
def services():
    """Manage Kubernetes services."""
    manager = ServiceManager()
    manager.navigate()

if __name__ == '__main__':
    cli()

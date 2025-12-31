"""
POP (Point of Presence) Topology Generator.

This generator creates network infrastructure for colocation center (POP) topologies.
It is invoked by Infrahub when a TopologyColocationCenter object is created or updated.

The generator performs the following steps:
1. Creates the physical site (LocationBuilding)
2. Sets up IP address pools for management and loopback networks
3. Creates a VLAN number pool for Layer 2 segmentation
4. Provisions network devices based on the design template
5. Creates loopback interfaces with allocated IPs for routing protocols
6. Establishes out-of-band management and console connections

This is a simpler topology compared to the DC generator - it does not include:
- Location hierarchy (pods, rows, racks)
- Rack assignment
- VTEP loopback pools (no VXLAN overlay)
"""

from infrahub_sdk.generator import InfrahubGenerator

from .common import TopologyCreator, clean_data


class PopTopologyGenerator(InfrahubGenerator):
    """
    Generate POP (Point of Presence) network topology infrastructure.

    This generator is triggered when a TopologyColocationCenter object is created
    in Infrahub. It uses the design elements and subnet allocations from the
    topology definition to create a complete, functional network infrastructure.

    Inherits from InfrahubGenerator which provides:
    - self.client: InfrahubClient for API operations
    - self.logger: Logger for operation tracking
    - self.branch: Branch name for isolated changes
    """

    async def generate(self, data: dict) -> None:
        """
        Generate POP topology from the provided design data.

        This is the main entry point called by Infrahub when the generator runs.
        The data parameter contains the GraphQL query result for the topology.

        Args:
            data: Raw GraphQL response containing topology configuration including:
                  - TopologyColocationCenter object with name, design, subnets
                  - design.elements: List of device specifications (role, quantity, template)
                  - management_subnet: Prefix for OOB management IPs
                  - technical_subnet: Prefix for loopback IPs
        """
        # Transform raw GraphQL response into clean Python data structures
        # This unwraps nested 'value', 'node', and 'edges' structures from GraphQL
        cleaned_data = clean_data(data)

        # Extract the first TopologyColocationCenter from the cleaned data
        # The query returns a list of topologies; we process the first one
        if isinstance(cleaned_data, dict):
            data = cleaned_data["TopologyColocationCenter"][0]
        else:
            raise ValueError("clean_data() did not return a dictionary")

        # Initialize the TopologyCreator with our context
        # This class orchestrates all infrastructure creation operations
        network_creator = TopologyCreator(
            client=self.client,  # Infrahub API client for creating objects
            log=self.logger,  # Logger for progress and debug output
            branch=self.branch,  # Branch for isolated changes (e.g., feature branch)
            data=data,  # Cleaned topology data with design elements
        )

        # Load and prepare topology data:
        # - Expands interface ranges (e.g., "Ethernet[1-48]" -> individual interfaces)
        # - Pre-loads groups and templates into local store for efficient access
        await network_creator.load_data()

        # Create the LocationBuilding (site) for this POP
        # This becomes the parent location for all devices in the topology
        await network_creator.create_site()

        # Build the list of IP address pools to create
        # Each pool will be used for automatic IP allocation to devices/interfaces
        subnets = []

        # Management subnet pool: Used for OOB (out-of-band) management IPs
        # These IPs are assigned to device primary_address for remote management
        if data.get("management_subnet"):
            subnets.append(
                {
                    "type": "Management",
                    "prefix_id": data["management_subnet"]["id"],
                }
            )

        # Technical subnet pool: Used for loopback interface IPs
        # These IPs are used for routing protocols (BGP router-id, etc.)
        if data.get("technical_subnet"):
            subnets.append(
                {
                    "type": "Loopback",
                    "prefix_id": data["technical_subnet"]["id"],
                }
            )

        # Create CoreIPAddressPool objects for each subnet type
        # These pools enable automatic IP allocation using allocate_next_ip_address()
        await network_creator.create_address_pools(subnets)

        # Create a CoreNumberPool for VLAN ID allocation (range 100-4000)
        # Used for automatic VLAN assignment to ServiceNetworkSegment objects
        await network_creator.create_L2_pool()

        # Create all network devices defined in the design template:
        # - Physical devices (switches, routers)
        # - Virtual devices
        # - Security devices (firewalls)
        # Each device gets: name, management IP, group membership, interfaces
        await network_creator.create_devices()

        # Create loopback0 interfaces on routing devices (spine, leaf, border_leaf, edge)
        # Each loopback gets an IP from the loopback_ip_pool for BGP/OSPF router-id
        await network_creator.create_loopback("loopback0")

        # Create management network cables between OOB switches and all devices
        # Connects management interfaces with even/odd pairing for redundancy
        await network_creator.create_oob_connections("management")

        # Create console server cables between console servers and all devices
        # Provides serial console access for device recovery and initial configuration
        await network_creator.create_oob_connections("console")

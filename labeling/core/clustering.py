"""
Spatial Intelligence: Groups nearby shapes and ID tags into a single 'Structural Hub'.
"""
import math
from config import Config

class StructuralHub:
    def __init__(self, x: float, y: float):
        self.x_sum = x
        self.y_sum = y
        self.count = 1
        self.candidates = []
        self.id = None
        self.id_label = None

    @property
    def centroid(self):
        return (self.x_sum / self.count, self.y_sum / self.count)

    def add(self, x: float, y: float):
        self.x_sum += x
        self.y_sum += y
        self.count += 1

class ClusteringService:
    def __init__(self, radius: float = Config.HUB_RADIUS):
        self.radius = radius
        self.hubs = []

    def find_or_create_hub(self, x: float, y: float):
        """Finds a hub within radius or creates a new one. Updates centroid."""
        for hub in self.hubs:
            hx, hy = hub.centroid
            dist = math.sqrt((x - hx)**2 + (y - hy)**2)
            if dist < self.radius:
                hub.add(x, y) # Update centroid as we group items
                return hub
        
        # None found, create new
        new_hub = StructuralHub(x, y)
        self.hubs.append(new_hub)
        return new_hub

    def get_nearby(self, x: float, y: float, search_radius: float):
        """Returns all hubs within a custom radius."""
        nearby = []
        for hub in self.hubs:
            hx, hy = hub.centroid
            dist = math.sqrt((x - hx)**2 + (y - hy)**2)
            if dist < search_radius:
                nearby.append(hub)
        return nearby

from __future__ import annotations
import torch
from torch import nn
from torch.nn import functional as F

class Tower(nn.Module):
    def __init__(self,dimensions):
        super().__init__();self.layers=nn.Sequential(nn.Linear(dimensions,128),nn.LayerNorm(128),nn.ReLU(),nn.Linear(128,64))
    def forward(self,value):return F.normalize(self.layers(value),dim=-1)

class MusicTwoTower(nn.Module):
    """User tower consumes a history profile; item tower consumes music metadata."""
    def __init__(self,dimensions):
        super().__init__();self.user_tower=Tower(dimensions);self.item_tower=Tower(dimensions)
    def forward(self,profiles,items):return self.user_tower(profiles),self.item_tower(items)

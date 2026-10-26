"""Inference for CatBoost's exported scalar symmetric trees with float splits."""
import json
import numpy as np

class PortableRanker:
    def __init__(self,path):
        data=json.loads(path.read_text(encoding="utf-8"));scale,bias=data["scale_and_bias"]
        if len(bias)!=1:raise ValueError("Only scalar ranking models are supported")
        self.scale=float(scale);self.bias=float(bias[0]);self.trees=[]
        self.dimensions=len(data["features_info"]["float_features"])
        for tree in data["oblivious_trees"]:
            splits=tree.get("splits") or [];leaves=np.asarray(tree["leaf_values"],dtype=np.float64)
            if len(leaves)!=2**len(splits):raise ValueError("Invalid symmetric tree")
            parsed=[]
            for split in splits:
                if split["split_type"]!="FloatFeature":raise ValueError("Only float splits are supported")
                parsed.append((int(split["float_feature_index"]),float(split["border"])))
            self.trees.append((parsed,leaves))
    def predict(self,features):
        features=np.asarray(features,dtype=np.float32)
        if features.ndim!=2 or features.shape[1]!=self.dimensions or not np.isfinite(features).all():raise ValueError("Invalid rank features")
        result=np.zeros(len(features),dtype=np.float64)
        for splits,leaves in self.trees:
            index=np.zeros(len(features),dtype=np.int32)
            for bit,(column,border) in enumerate(splits):index|=(features[:,column]>border).astype(np.int32)<<bit
            result+=leaves[index]
        return result*self.scale+self.bias

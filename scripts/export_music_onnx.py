"""Build-time export only: desktop/mobile inference needs no Python interpreter."""
from pathlib import Path
import argparse,json,struct,shutil
import numpy as np
import onnx
from onnx import helper as h,numpy_helper as nh,TensorProto as T
from catboost import CatBoostRanker


def export(source,target):
    target.mkdir(parents=True,exist_ok=True)
    w=dict(np.load(source/'user_tower.npz'))
    dims=w['layers.0.weight'].shape[1]
    constants=[nh.from_array(value.astype(np.float32),name) for name,value in w.items()]
    constants += [nh.from_array(np.array(1e-5,dtype=np.float32),'epsilon'),nh.from_array(np.array(1e-8,dtype=np.float32),'norm_min')]
    nodes=[h.make_node('Gemm',['profile','layers.0.weight','layers.0.bias'],['hidden'],transB=1),
        h.make_node('ReduceMean',['hidden'],['mean'],axes=[1],keepdims=1),h.make_node('Sub',['hidden','mean'],['center']),
        h.make_node('Mul',['center','center'],['squares']),h.make_node('ReduceMean',['squares'],['variance'],axes=[1],keepdims=1),
        h.make_node('Add',['variance','epsilon'],['stabilized']),h.make_node('Sqrt',['stabilized'],['sigma']),
        h.make_node('Div',['center','sigma'],['normalized']),h.make_node('Mul',['normalized','layers.1.weight'],['scaled']),
        h.make_node('Add',['scaled','layers.1.bias'],['affine']),h.make_node('Relu',['affine'],['relu']),
        h.make_node('Gemm',['relu','layers.3.weight','layers.3.bias'],['embedding'],transB=1),
        h.make_node('ReduceL2',['embedding'],['norm'],axes=[1],keepdims=1),h.make_node('Max',['norm','norm_min'],['safe_norm']),
        h.make_node('Div',['embedding','safe_norm'],['query'])]
    graph=h.make_graph(nodes,'RiffunaMusicUserTower',[h.make_tensor_value_info('profile',T.FLOAT,[None,dims])],[h.make_tensor_value_info('query',T.FLOAT,[None,64])],constants)
    model=h.make_model(graph,opset_imports=[h.make_opsetid('',16)],producer_name='Riffuna');model.ir_version=8
    onnx.checker.check_model(model);onnx.save(model,target/'user_tower.onnx')
    ranker=CatBoostRanker();ranker.load_model(str(source/'ranker.cbm'))
    ranker.save_model(str(target/'ranker.onnx'),format='onnx',export_parameters={'onnx_domain':'riffuna.music','onnx_model_version':1})
    # CatBoost emits [N,1] but declares [N]; keep the ONNX contract accurate.
    ranker_model=onnx.load(target/'ranker.onnx')
    ranker_model.graph.output[0].type.tensor_type.shape.dim.add().dim_value=1
    onnx.save(ranker_model,target/'ranker.onnx')
    data=np.load(source/'catalog_vectors.npz');features=data['features'];vectors=data['vectors'];pop=data['popularity'];gd=int(data['genre_dim'])
    with (target/'catalog.bin').open('wb') as out:
        out.write(b'RIFMUS01');out.write(struct.pack('>4i',len(features),features.shape[1],gd,vectors.shape[1]))
        for row in features:
            columns=np.flatnonzero(row);out.write(struct.pack('>i',len(columns)))
            for column in columns:out.write(struct.pack('>Hf',int(column),float(row[column])))
        out.write(vectors.astype('>f4').tobytes());out.write(pop.astype('>f4').tobytes())
    for name in ('catalog.json','genre_names.json','manifest.json'):shutil.copy2(source/name,target/name)
    shutil.copy2(Path(__file__).resolve().parents[1]/'LICENSES'/'Music4All-Onion-ATTRIBUTION.json',target/'ATTRIBUTION.json')
    print(json.dumps({'tracks':len(features),'feature_dim':features.shape[1],'genre_dim':gd,'files':{p.name:p.stat().st_size for p in target.iterdir()}}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--target',type=Path,required=True);args=parser.parse_args();export(args.source,args.target)

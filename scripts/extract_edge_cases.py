import os
import json
import glob
import shutil
from pathlib import Path
from datetime import datetime

class EdgeCaseExtractor:
    def __init__(self, source_folders, target_dir="tests/edge_cases"):
        self.source_folders = source_folders
        self.target_dir = Path(target_dir)
        self.pred_dir = self.target_dir / "predictions"
        self.rev_dir = self.target_dir / "reviews"
        self.img_dir = self.target_dir / "images"
        self.image_source_dir = Path("data/images")
        self.manifest_path = self.target_dir / "manifest.json"
        
        # Ensure directories exist
        for d in [self.pred_dir, self.rev_dir, self.img_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def extract(self):
        edge_cases = []
        
        for folder in self.source_folders:
            folder_path = Path(folder)
            if not folder_path.exists():
                continue
                
            for review_file in folder_path.glob("review_*.json"):
                with open(review_file, 'r') as f:
                    try:
                        data = json.load(f)
                    except:
                        continue
                        
                analysis = data.get('analysis', {})
                pred_content = data.get('prediction', {}).get('content', {})
                
                if not isinstance(analysis, dict): continue
                
                score = analysis.get('evaluation_score', 100)
                result = analysis.get('tp_sl_result', 'NEITHER')
                timestamp = pred_content.get('timestamp')
                symbol = pred_content.get('config_context', {}).get('symbol', 'BTCUSDT')
                
                if result == 'SL_HIT' or score <= 25:
                    source_pred_file = data.get('prediction', {}).get('source', '')
                    pred_path = folder_path / source_pred_file
                    
                    if timestamp and pred_path.exists():
                        # Parse timestamp to construct image names
                        target_img = []
                        try:
                            dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
                            for tf in ['15m', '1h']:
                                img_filename = f"{symbol}_{tf}_{dt.strftime('%Y%m%d_%H%M%S')}Z_chart.png"
                                source_img_path = self.image_source_dir / img_filename
                                target_img_path = self.img_dir / img_filename
                                
                                # Move if original exists
                                if source_img_path.exists():
                                    shutil.move(str(source_img_path), str(target_img_path))
                                    target_img.append(img_filename)
                        except ValueError:
                            pass

                        # Move JSON files
                        target_rev = self.rev_dir / review_file.name
                        target_pred = self.pred_dir / source_pred_file
                        
                        # Use move instead of copy to delete originals in data/
                        shutil.move(str(review_file), str(target_rev))
                        shutil.move(str(pred_path), str(target_pred))

                        edge_cases.append({
                            'timestamp': timestamp,
                            'symbol': symbol,
                            'score': score,
                            'result': result,
                            'review_file': review_file.name,
                            'prediction_file': source_pred_file,
                            'image_files': target_img,
                            'original_source': folder
                        })

        edge_cases.sort(key=lambda x: x['score'])
        
        # Build manifest
        manifest = {
            'total': len(edge_cases),
            'description': "Curated extreme edge cases (SL_HIT or score <= 25) for prompt optimization re-testing.",
            'last_updated': datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            'samples': edge_cases
        }
        
        with open(self.manifest_path, 'w') as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)
            
        print(f"Extraction complete. {len(edge_cases)} edge cases saved to {self.target_dir}/manifest.json")

if __name__ == "__main__":
    sources = ['data/archive_training_v1', 'data/archive_training_v1.1']
    extractor = EdgeCaseExtractor(sources)
    extractor.extract()

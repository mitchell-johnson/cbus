#!/usr/bin/env python
"""
Memory leak analysis script
This script helps analyze memory_snapshot files generated by the memory profiling tools.
"""

import os
import sys
import glob
import re
from datetime import datetime

def extract_stats_from_file(filename):
    """Extract memory statistics from a memory diff file"""
    stats = []
    
    with open(filename, 'r') as f:
        lines = f.readlines()
        
    for line in lines:
        # Look for lines with memory size info (example format: "path/to/file.py:123: size=1234 KiB (+567 KiB)")
        match = re.search(r'(.+):(\d+): size=(\d+) ([KMG]iB) \(\+(\d+) ([KMG]iB)\)', line)
        if match:
            file_path = match.group(1)
            line_num = int(match.group(2))
            total_size = int(match.group(3))
            total_unit = match.group(4)
            diff_size = int(match.group(5))
            diff_unit = match.group(6)
            
            # Convert to bytes for consistent comparison
            total_bytes = convert_to_bytes(total_size, total_unit)
            diff_bytes = convert_to_bytes(diff_size, diff_unit)
            
            stats.append({
                'file': file_path,
                'line': line_num,
                'total_size': total_bytes,
                'diff_size': diff_bytes,
                'total_display': f"{total_size} {total_unit}",
                'diff_display': f"{diff_size} {diff_unit}"
            })
    
    return stats

def convert_to_bytes(size, unit):
    """Convert size with unit to bytes"""
    multipliers = {
        'KiB': 1024,
        'MiB': 1024*1024,
        'GiB': 1024*1024*1024
    }
    return size * multipliers.get(unit, 1)

def find_potential_leaks(stats_list, min_occurrences=3, min_growth=1024*50):
    """Find lines that consistently grow in memory usage"""
    # Group stats by file and line
    line_stats = {}
    
    for stats in stats_list:
        for stat in stats:
            key = f"{stat['file']}:{stat['line']}"
            if key not in line_stats:
                line_stats[key] = []
            line_stats[key].append(stat)
    
    # Find lines that appear multiple times and show consistent growth
    potential_leaks = []
    
    for key, stats in line_stats.items():
        if len(stats) >= min_occurrences:
            # Check if memory consistently grows
            is_growing = True
            total_growth = stats[-1]['total_size'] - stats[0]['total_size']
            
            if total_growth >= min_growth:
                potential_leaks.append({
                    'location': key,
                    'occurrences': len(stats),
                    'initial_size': stats[0]['total_display'],
                    'final_size': stats[-1]['total_display'],
                    'growth': format_bytes(total_growth),
                    'stats': stats
                })
    
    # Sort by total growth
    potential_leaks.sort(key=lambda x: sum(stat['diff_size'] for stat in x['stats']), reverse=True)
    
    return potential_leaks

def format_bytes(size_bytes):
    """Format bytes into human-readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024*1024:
        return f"{size_bytes/1024:.2f} KiB"
    elif size_bytes < 1024*1024*1024:
        return f"{size_bytes/(1024*1024):.2f} MiB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GiB"

def main():
    """Main function to analyze memory snapshots"""
    snapshot_dir = "memory_snapshots"
    
    if not os.path.exists(snapshot_dir):
        print(f"Error: Snapshot directory '{snapshot_dir}' not found.")
        print("Run memory profiling scripts first to generate memory snapshots.")
        return 1
    
    # Find all memory diff files
    diff_files = glob.glob(f"{snapshot_dir}/memory_diff_*.txt")
    final_files = glob.glob(f"{snapshot_dir}/memory_final_*.txt")
    all_files = diff_files + final_files
    
    if not all_files:
        print(f"No memory snapshot files found in '{snapshot_dir}'.")
        print("Run memory profiling scripts first to generate memory snapshots.")
        return 1
    
    # Sort files by modification time
    all_files.sort(key=os.path.getmtime)
    
    print(f"Found {len(all_files)} memory snapshot files")
    
    # Extract stats from all files
    all_stats = []
    for filename in all_files:
        stats = extract_stats_from_file(filename)
        if stats:
            file_time = datetime.fromtimestamp(os.path.getmtime(filename))
            print(f"  {os.path.basename(filename)} ({file_time.strftime('%Y-%m-%d %H:%M:%S')}): {len(stats)} entries")
            all_stats.append(stats)
    
    # Find potential memory leaks
    potential_leaks = find_potential_leaks(all_stats)
    
    if not potential_leaks:
        print("\nNo significant memory leaks detected.")
        return 0
    
    # Display potential leaks
    print(f"\nFound {len(potential_leaks)} potential memory leaks:")
    print("-" * 80)
    
    for i, leak in enumerate(potential_leaks[:20], 1):
        print(f"{i}. {leak['location']}")
        print(f"   Occurrences: {leak['occurrences']}")
        print(f"   Growth: {leak['initial_size']} → {leak['final_size']} (total growth: {leak['growth']})")
        print("")
    
    # Write detailed report
    report_file = "memory_leak_report.txt"
    with open(report_file, 'w') as f:
        f.write(f"Memory Leak Analysis Report\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Based on {len(all_files)} memory snapshots\n\n")
        
        f.write(f"Top {len(potential_leaks)} Potential Memory Leaks:\n")
        f.write("-" * 80 + "\n")
        
        for i, leak in enumerate(potential_leaks, 1):
            f.write(f"{i}. {leak['location']}\n")
            f.write(f"   Occurrences: {leak['occurrences']}\n")
            f.write(f"   Growth: {leak['initial_size']} → {leak['final_size']} (total growth: {leak['growth']})\n")
            f.write(f"   Growth pattern:\n")
            
            for j, stat in enumerate(leak['stats']):
                f.write(f"     {j+1}. Size: {stat['total_display']} (change: +{stat['diff_display']})\n")
            
            f.write("\n")
    
    print(f"Detailed report saved to {report_file}")
    return 0

if __name__ == "__main__":
    sys.exit(main()) 
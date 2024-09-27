if [ -z "$1" ]; then
    echo "Usage: $0 test_name"
    exit 1
fi

test_dir=$(dirname "$(realpath $0)")/roundtrip/$1
echo $test_dir
mkdir -p $test_dir

cat > $test_dir/project.create.yml <<- EOM
project:
  name: Test Project
  course:
    name: Test Course
    semester: Summer
    year: 2014
  settings:
EOM

cp $test_dir/project.create.yml $test_dir/project.update.yml
cp $test_dir/project.create.yml $test_dir/project.create.expected.yml
cp $test_dir/project.update.yml $test_dir/project.update.expected.yml

echo "relative" | cat > $test_dir/deadline_cutoff_preference
